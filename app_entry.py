# -*- coding: utf-8 -*-
"""打包后的程序入口（由 PyInstaller 生成的 exe 调用）。

与源码模式（main.py）的区别：
  * 没有控制台窗口（GUI 模式打包），所有输出写日志文件；
  * 异常不再用 tkinter 弹窗（tkinter 可能被裁掉），而是写日志 + 用 Web 界面提示；
  * 单实例：已在运行时直接激活已开的服务，不再起第二个服务。

「单实例」用**命名互斥体**判定，不用端口探测。
原因：源码版（启动.vbs / main.py）和安装版会各起一个服务，如果用端口判定，
源码版一旦占住 8760，安装版每次双击都会命中单实例 → 只会用浏览器打开、
**永远不弹软件窗口**（用户看到的就是「双击了没反应」）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 打包后 sys.stdout/sys.stderr 是 None，任何 print 都会抛异常。
# 保留一份原始引用，诊断时还能把日志打到控制台。
_ORIG_STDOUT = sys.stdout
try:
    _devnull = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = _devnull
    sys.stderr = _devnull
except Exception:
    pass


def log_path() -> str:
    """日志文件：%APPDATA%\\企业信用截图工具\\运行.log。

    这里刻意不 import 项目内的任何模块：打包后如果某个模块导入失败，
    日志函数本身不能跟着挂掉，否则连出错原因都记录不下来。
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "企业信用截图工具", "运行.log")


def write_log(text: str) -> None:
    """追加写日志（失败也不能让程序崩）。"""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("---- %s ----\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass
    # 有真实控制台时同步输出，便于命令行排错
    if _ORIG_STDOUT is not None:
        try:
            _ORIG_STDOUT.write(text + "\n")
            _ORIG_STDOUT.flush()
        except Exception:
            pass


#: 打包版的单实例互斥体名（与源码版解耦，两者可以并存）
MUTEX_NAME = "Local\\CreditShotPackaged"

#: 软件窗口标题（与 desktop_window.APP_TITLE 一致）
APP_TITLE = "企业信用一键截图工具"

#: 互斥体句柄必须一直留着，否则会被 GC 关闭 → 锁失效
_mutex_handle = None


def _acquire_single_instance() -> bool:
    """取得打包版独占锁。返回 True = 本次是首个实例，应该正常启动。

    用命名互斥体而不是端口：端口会被源码版占住，导致安装版永远起不来窗口。
    """
    global _mutex_handle
    try:
        import ctypes
        from ctypes import wintypes

        k = ctypes.windll.kernel32
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                    wintypes.LPCWSTR]
        handle = k.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True          # 创建失败就别拦着用户，让他正常启动
        _mutex_handle = handle  # 留住句柄
        already = (k.GetLastError() == 183)   # ERROR_ALREADY_EXISTS
        return not already
    except Exception:
        return True


def _find_app_window():
    """找出本程序的软件窗口句柄；找不到返回 None。

    标题必须**精确匹配**：浏览器窗口的标题是
    「企业信用一键截图工具 - 用户配置 1 - Microsoft Edge」，
    用包含匹配会误抓到浏览器。
    """
    try:
        import ctypes
        from ctypes import wintypes

        u = ctypes.windll.user32
        hit = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, lparam):
            if not u.IsWindowVisible(hwnd):
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.strip() == APP_TITLE:
                hit.append(hwnd)
                return False
            return True

        u.EnumWindows(cb, 0)
        return hit[0] if hit else None
    except Exception:
        return None


def _focus_app_window() -> bool:
    """把本程序的软件窗口恢复到前台。成功返回 True。"""
    hwnd = _find_app_window()
    if not hwnd:
        return False
    try:
        import ctypes

        u = ctypes.windll.user32
        u.ShowWindow(hwnd, 9)        # SW_RESTORE：从最小化恢复
        u.SetForegroundWindow(hwnd)
        # SetForegroundWindow 常被系统拒绝，临时挂到目标线程再试一次
        fg = u.GetForegroundWindow()
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        tgt = u.GetWindowThreadProcessId(hwnd, None)
        if fg and tgt and cur != tgt:
            u.AttachThreadInput(cur, tgt, True)
            u.SetForegroundWindow(hwnd)
            u.AttachThreadInput(cur, tgt, False)
        return True
    except Exception:
        return False


def _focus_browser_window(timeout: float = 6.0) -> bool:
    """把刚打开的浏览器窗口置前。

    explorer.exe 打开的窗口默认不一定在前台，用户会以为「双击了没反应」。
    """
    try:
        import ctypes
        import time
        from ctypes import wintypes

        u = ctypes.windll.user32
        deadline = time.time() + timeout
        while time.time() < deadline:
            hit = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, lparam):
                if not u.IsWindowVisible(hwnd):
                    return True
                n = u.GetWindowTextLengthW(hwnd)
                if not n:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value
                if ("Microsoft Edge" in title or "Chrome" in title) \
                        and "企业信用" in title:
                    hit.append(hwnd)
                    return False
                return True

            u.EnumWindows(cb, 0)
            if hit:
                u.ShowWindow(hit[0], 9)
                u.SetForegroundWindow(hit[0])
                return True
            time.sleep(0.4)
        return False
    except Exception:
        return False


def _open_in_browser(url: str) -> None:
    """用系统默认浏览器打开界面，并尽量把窗口置前。"""
    try:
        # 交给 explorer 打开：浏览器与本程序无父子关系，
        # 用 webbrowser / ShellExecute 都可能把本进程一起带走。
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["explorer.exe", url],
                         creationflags=flags, close_fds=True)
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    _focus_browser_window()


def _existing_service_port(start: int = 8760, tries: int = 80):
    """探测本机是否已经有本服务在跑；返回端口号或 None。"""
    import socket
    import urllib.request
    # 本机可能配了 HTTP_PROXY，会把 127.0.0.1 的请求也代理走 → 必须禁用
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in range(start, start + tries):
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                continue          # 端口没被占用，肯定不是本服务
        try:
            with opener.open("http://127.0.0.1:%d/api/ping" % port,
                             timeout=1.0) as r:
                body = r.read()   # 只能读一次：第二次返回空
            # 必须带 app 标识才算「是本程序」，否则会误判同端口的其它服务
            if b'"app":"credit-shot"' in body.replace(b" ", b""):
                return port
        except Exception:
            continue
    return None


def _open_existing(port: int) -> None:
    """已有实例在跑：把它的界面推到前台，然后结束本进程。

    优先聚焦**软件窗口**（用户要的就是软件窗口，不是浏览器）；
    找不到窗口才退回到浏览器打开。
    """
    url = "http://127.0.0.1:%d/" % port
    if _focus_app_window():
        write_log("检测到程序已在运行（端口 %d），已将其窗口置于前台。" % port)
        return
    _open_in_browser(url)
    write_log("检测到程序已在运行（端口 %d），已用浏览器打开其界面。" % port)


def main() -> int:
    # 1) 单实例判定（按可执行体，不按端口）
    if not _acquire_single_instance():
        # 打包版已在运行 → 把它的软件窗口顶到前台
        if _focus_app_window():
            write_log("程序已在运行，已将其窗口置于前台。")
            return 0
        # 找不到窗口（异常情况）→ 复用已有服务并用浏览器打开
        port = _existing_service_port()
        if port:
            _open_existing(port)
            return 0
        # 互斥体可能是残留的，继续正常启动

    # 2) 正常启动
    write_log("程序启动。")
    try:
        import desktop_window
        from web.server import serve

        if not desktop_window.has_pywebview():
            # 没装 pywebview（源码模式或打包漏收）→ 回退到外部浏览器
            write_log("未找到 pywebview，改用系统浏览器打开界面。")
            serve(host="127.0.0.1", open_ui=True,
                  on_ready=lambda url: write_log("服务已就绪：%s" % url))
            return 0

        # 3) 起服务 + 开软件窗口（窗口关闭即退出）
        write_log("准备启动本地服务与软件窗口…")
        # 端口在这里定一次，服务与窗口都用同一个，避免两边各算一次对不上
        port = _pick_port()
        url = "http://127.0.0.1:%d/" % port
        rc = desktop_window.run_with_window(
            url,
            lambda: serve(host="127.0.0.1", port=port, open_ui=False,
                          on_ready=lambda u: write_log("服务已就绪：%s" % u)))
        write_log("程序已退出（返回码 %d）。" % rc)
        return rc
    except KeyboardInterrupt:
        write_log("用户中断，已退出。")
    except BaseException:
        # BaseException：打包后 SystemExit / OSError 之类也要落到日志里，
        # 否则 windowed 模式下进程会「静默消失」，用户只看到程序没反应。
        write_log(traceback.format_exc())
        return 1


def _pick_port() -> int:
    """挑一个可用端口（与服务实际监听的一致）。"""
    from web.server import find_free_port
    return find_free_port()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        # 正常的退出路径（单实例命中、或 main() 返回退出码），不算错误
        raise
    except BaseException:
        # 最后一道保险：连 main() 都进不去时，也要把原因写进日志。
        # 否则打包成 windowed 程序后，用户只会看到「双击了但什么都没发生」。
        try:
            write_log(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
