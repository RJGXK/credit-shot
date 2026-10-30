# -*- coding: utf-8 -*-
"""core/browser.py —— 浏览器会话（启动 + CDP 接管 + 收尾）。

为什么不用 playwright 自带的 launch()：
信用中国等站点的前置 WAF 会针对 Playwright 默认启动参数直接返回 412 空页面，
用「常规 flags 启动 + --remote-debugging-port + CDP 接管」的方式页面才能正常渲染，
同时仍可用 Playwright 的原生整页截图等 API。

资料目录是固定的（要保留裁判文书网等站点的登录态），而 Edge 对同一资料目录
只允许一个实例：旧实例还在时新进程会秒退，导致「第二次运行必失败」。
因此这里先尝试复用已打开的实例，运行结束再把本次启动的进程收干净。
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from typing import Optional

__all__ = ["BrowserSession", "BROWSER_EXE", "browser_candidates"]

# 浏览器可执行文件的常见安装位置（不写死用户名，才能在别的电脑上跑）
_COMMON_BROWSER_DIRS = {
    "Edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application",
        r"C:\Program Files\Microsoft\Edge\Application",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application",
    ],
    "Chrome": [
        r"%LOCALAPPDATA%\Google\Chrome\Application",
        r"C:\Program Files\Google\Chrome\Application",
        r"C:\Program Files (x86)\Google\Chrome\Application",
    ],
}

#: 会影响浏览器行为/外观的启动参数（不含端口与资料目录）。
#: 改这里等于改变「指纹」：旧实例会被判定为过时并重启，
#: 否则升级后用户会一直复用那个带着旧标记（顶部黄条）的实例。
LAUNCH_FLAGS = [
    "--start-maximized",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-service-autorun",
]

# 浏览器主程序文件名（Edge/Chrome 都是 exe 后缀的同名文件）
_BROWSER_EXE_NAMES = {"Edge": "msedge.exe", "Chrome": "chrome.exe"}

# 兜底：注册表里查 App Paths（能覆盖装在非标准位置的版本）
_REGISTRY_EXE_KEYS = {
    "Edge": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    "Chrome": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
}

# 运行时填充的候选路径缓存（第一次调用时探测，之后直接复用）
_BROWSER_EXE = {
    "Edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "Chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}


def _expand(path: str) -> str:
    """展开 %LOCALAPPDATA% 之类的环境变量。"""
    return os.path.expandvars(path)


def _from_registry(kind: str) -> Optional[str]:
    """从注册表 App Paths 里找浏览器（覆盖装在非标准目录的情况）。"""
    try:
        import winreg
    except ImportError:
        return None
    key_path = _REGISTRY_EXE_KEYS.get(kind)
    if not key_path:
        return None
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as k:
                    value, _ = winreg.QueryValueEx(k, "")
                    if value and os.path.exists(value):
                        return value
            except OSError:
                continue
    return None


def browser_candidates(kind: str) -> list:
    """列出某个浏览器的全部候选可执行文件路径（按优先级）。

    顺序：内置常见路径 → 常见目录扫描 → 注册表 App Paths。
    全部动态探测，所以拷到别的电脑上也能找到浏览器。
    """
    if kind not in _BROWSER_EXE:
        return []
    exe_name = _BROWSER_EXE_NAMES.get(kind, "")
    found = list(_BROWSER_EXE.get(kind, []))

    # 常见目录里直接找主程序
    for d in _COMMON_BROWSER_DIRS.get(kind, []):
        p = os.path.join(_expand(d), exe_name)
        if os.path.exists(p) and p not in found:
            found.append(p)

    # 注册表兜底
    reg = _from_registry(kind)
    if reg and reg not in found:
        found.append(reg)
    return found


class BrowserSession:
    """一个浏览器会话的完整生命周期。"""

    def __init__(self, kind: str, log=print, timeout: int = 30):
        self.kind = kind
        self.log = log
        self.timeout = timeout
        self.proc = None            # 本次启动的浏览器进程（结束时负责关闭）
        self.pw = None              # playwright 实例
        self.browser_obj = None     # CDP 浏览器对象
        self.ctx = None             # 浏览器上下文
        self.page = None            # 引擎当前持有的主页（close() 返回的那个）

    @staticmethod
    def free_port(start: int = 9333) -> int:
        for p in range(start, start + 40):
            with socket.socket() as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
        return start

    @staticmethod
    def find_exe(kind: str) -> Optional[str]:
        """找到该浏览器的主程序；找不到返回 None。"""
        for path in browser_candidates(kind):
            if os.path.exists(path):
                return path
        return None


    def open(self):
        """启动浏览器并用 CDP 接管。

        为什么不用 playwright 自带的 launch()：
        信用中国等站点的前置 WAF 会针对 Playwright 默认启动参数直接返回 412 空页面；
        用「常规 flags 启动 + --remote-debugging-port + CDP 接管」的方式，页面能正常渲染，
        同时仍可用 Playwright 的原生整页截图等 API。

        资料目录是固定的（要保留裁判文书网等站点的登录态），而 Edge 对同一资料目录
        只允许一个实例：旧实例还在时新进程会秒退，导致"第二次运行必失败"。
        因此这里先尝试复用已打开的实例，运行结束再把本次启动的进程收干净。
        """
        kind = self.kind if self.kind in _BROWSER_EXE else "Chrome"
        exe = self.find_exe(kind)
        if not exe:
            raise RuntimeError("未找到 %s 可执行文件，请确认电脑上已安装 %s"
                               % (kind, kind))

        profile = os.environ.get("CREDIT_SHOT_PROFILE") or os.path.join(
            os.path.expanduser("~"), ".credit_shot_profile", kind)
        os.makedirs(profile, exist_ok=True)

        # 1) 复用已经开着、且带调试端口的同资料目录实例。
        # 但**必须先确认它是不是用当前这套启动参数起的**：
        # 老版本实例可能带着 --disable-blink-features=AutomationControlled
        # 之类的标记（浏览器顶部会有黄条，看着就像自动化）。参数变了就杀掉重开，
        # 否则升级后用户永远复用到那个"脏"实例。
        sig = self._launch_signature()
        reuse_port = self.read_reusable_port(profile)
        if reuse_port:
            old_sig = self.read_launch_sig(profile)
            if old_sig != sig:
                self.log("  ↻ 检测到启动参数已更新（旧实例带过时的命令行标记），重启%s…" % kind)
                self.kill_stale_browsers(profile)
                time.sleep(2.0)
                reuse_port = None
        if reuse_port:
            self.log("复用已打开的 %s（调试端口 %d）…" % (kind, reuse_port))
            try:
                return self.connect_cdp(reuse_port)
            except Exception as exc:
                # 10:57 日志实锤：旧实例刚被杀、新实例还没起来时，
                # 复用会报 connect ECONNREFUSED。这里清场后**重启**而不是直接崩。
                self.log("  ⚠ 复用失败（%s），清理旧实例后重新启动浏览器"
                         % str(exc).splitlines()[0][:60])
                try:
                    if self.pw is not None:
                        self.pw.stop()
                except Exception:
                    pass
                self.pw = None
                self.browser_obj = None
                self.ctx = None
                self.kill_stale_browsers(profile)
                time.sleep(2.0)

        # 2) 重新启动
        port = self.free_port()
        args = [
            exe,
            "--remote-debugging-port=%d" % port,
            "--user-data-dir=%s" % profile,
            # 不要再加 --disable-blink-features=AutomationControlled：
            # Edge/Chrome 会弹出「您使用的是不受支持的命令行标记」黄色提示条，
            # 既影响截图观感，也等于自报「这是自动化浏览器」。
            # 实测用 CDP 接管并不会把 navigator.webdriver 置真，
            # 这个标记纯属多余，去掉后浏览器与正常窗口完全一致。
        ] + LAUNCH_FLAGS + ["about:blank"]
        self.log("启动 %s（调试端口 %d，专用资料目录可保留登录态）…" % (kind, port))
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.proc = proc
        try:
            self.write_launch_sig(profile, sig)
        except Exception:
            pass

        endpoint = "http://127.0.0.1:%d" % port
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline:
            if self.probe_cdp(port):
                ready = True
                break
            if proc.poll() is not None:
                break                      # 进程已退出（多半是资料目录被旧实例占用）
            time.sleep(1)
        if not ready:
            # 旧实例占着资料目录：清掉它再试一次
            self.log("  ⚠ 浏览器未能就绪，尝试清理占用资料目录的旧实例…")
            self.kill_stale_browsers(profile)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            port = self.free_port()
            args[1] = "--remote-debugging-port=%d" % port
            self.log("重新启动 %s（调试端口 %d）…" % (kind, port))
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.proc = proc
            deadline = time.time() + 30
            while time.time() < deadline:
                if self.probe_cdp(port):
                    ready = True
                    break
                if proc.poll() is not None:
                    break
                time.sleep(1)
        if not ready:
            raise RuntimeError("浏览器调试端口未就绪")

        try:
            with open(self.port_file(profile), "w", encoding="utf-8") as f:
                f.write(str(port))
        except Exception:
            pass
        try:
            return self.connect_cdp(port)
        except Exception as exc:
            # 刚探测就绪仍可能接管失败（浏览器还在初始化）：歇一下再试一次
            self.log("  ⚠ 接管刚启动的浏览器失败（%s），2 秒后重试"
                     % str(exc).splitlines()[0][:60])
            try:
                if self.pw is not None:
                    self.pw.stop()
            except Exception:
                pass
            self.pw = None
            self.browser_obj = None
            self.ctx = None
            time.sleep(2.0)
            return self.connect_cdp(port)


    @staticmethod
    def port_file(profile: str) -> str:
        return os.path.join(profile, ".debug_port")

    @staticmethod
    def sig_file(profile: str) -> str:
        return os.path.join(profile, ".launch_sig")

    @staticmethod
    def _launch_signature() -> str:
        """当前启动参数的指纹（只算行为参数，端口/资料目录不参与）。"""
        import hashlib
        return hashlib.md5(("|".join(LAUNCH_FLAGS)).encode("utf-8")).hexdigest()

    @classmethod
    def read_launch_sig(cls, profile: str) -> str:
        try:
            with open(cls.sig_file(profile), "r", encoding="utf-8") as f:
                return (f.read() or "").strip()
        except Exception:
            return ""

    @classmethod
    def write_launch_sig(cls, profile: str, sig: str) -> None:
        try:
            with open(cls.sig_file(profile), "w", encoding="utf-8") as f:
                f.write(sig)
        except Exception:
            pass


    @staticmethod
    def probe_cdp(port: int, timeout: float = 1.5) -> bool:
        import urllib.request

        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port,
                                        timeout=timeout):
                return True
        except Exception:
            return False


    def read_reusable_port(self, profile: str) -> Optional[int]:
        """读取上次记录的调试端口，若浏览器还活着就可以直接接管。"""
        try:
            with open(self.port_file(profile), "r", encoding="utf-8") as f:
                port = int((f.read() or "0").strip())
        except Exception:
            return None
        if 0 < port < 65536 and self.probe_cdp(port):
            return port
        return None


    def kill_stale_browsers(self, profile: str) -> int:
        """关掉占用同一资料目录、但没有调试端口的浏览器实例。"""
        try:
            script = (
                "$p='%s';"
                "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or "
                "Name='chrome.exe'\" | Where-Object { $_.CommandLine -like ('*'+$p+'*') } "
                "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction "
                "SilentlyContinue; $_.ProcessId }"
            ) % profile.replace("'", "''")
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25)
            pids = [x.strip() for x in (out.stdout or b"").decode("utf-8", "ignore").split()
                    if x.strip().isdigit()]
            if pids:
                self.log("  已清理旧浏览器实例：%s" % "、".join(pids))
            return len(pids)
        except Exception:
            return 0


    def close(self) -> None:
        """收干净浏览器：断开 CDP + 结束本次启动的进程树。

        不结束进程的话，资料目录会被占用，下一次运行必然启动失败。
        """
        proc = self.proc
        self.proc = None
        browser, self.browser_obj = self.browser_obj, None
        pw, self.pw = self.pw, None
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass
        self.ctx = None
        if proc is not None and proc.poll() is None:
            pid = proc.pid
            for args in (["taskkill", "/PID", str(pid), "/T"],
                         ["taskkill", "/PID", str(pid), "/T", "/F"]):
                try:
                    subprocess.run(args, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=20)
                except Exception:
                    pass
                time.sleep(1.5)
                try:
                    if proc.poll() is not None:
                        break
                except Exception:
                    break
            self.log("浏览器已关闭（进程 %s）" % pid)


    def connect_cdp(self, port: int):
        """用 CDP 接管指定端口上的浏览器。"""
        from playwright.sync_api import sync_playwright

        endpoint = "http://127.0.0.1:%d" % port
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(endpoint)
        self.pw = pw
        self.browser_obj = browser
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        self.ctx = ctx
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # 记住引擎持有的主页：平台处理器的「清理多余标签页」必须保住它
        # （v2.2.7 实测把它关掉后后续所有采集组全链 Target page closed）
        self.page = page
        try:
            page.set_default_timeout(self.timeout * 1000)
        except Exception:
            pass
        return pw, browser, ctx, page
