# -*- coding: utf-8 -*-
"""验证打包后的 exe 能否真正干活。

    python tools/verify_exe.py

检查项：
  1. exe 存在、关键资源（前端静态文件 / playwright 驱动 / pywin32）都在包里；
  2. 双击 exe 后本机服务能起来（/api/ping 返回带 app 标识）；
  3. 首页能正常返回 HTML（含品牌标题）；
  4. 前端静态资源（css/js）能访问；
  5. 单实例：再启动一次不会起第二个服务；
  6. 凭据目录落在 %APPDATA% 而不是 exe 目录（打包后仍可写、升级不丢）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "企业信用截图工具")
EXE = os.path.join(DIST, "企业信用截图工具.exe")

PASS, FAIL = [], []

# 本机可能有 HTTP_PROXY 指向代理服务器，会把 127.0.0.1 的请求也劫持走，
# 导致「服务明明起来了却探测不到」。这里显式禁用代理。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("✔" if ok else "✘", name,
                       ("  —— " + detail) if detail else ""))


def http(path: str, timeout: float = 3.0):
    """请求本机服务，返回 (状态码, 正文)。"""
    for port in range(8760, 8840):
        try:
            with _OPENER.open("http://127.0.0.1:%d%s" % (port, path),
                              timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception:
            continue
    return None, b""


def find_service_port(max_wait: float = 90.0):
    """等本服务起来，返回端口号。

    探测要「有耐心」：exe 是 windowed 模式，启动要先解包 _MEIPASS（近 200MB），
    再初始化 playwright/pywin32，端口真正开始监听要 12~15 秒。
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        for port in range(8760, 8840):
            try:
                with _OPENER.open("http://127.0.0.1:%d/api/ping" % port,
                                  timeout=1.0) as r:
                    body = r.read().replace(b" ", b"")
                if b'"app":"credit-shot"' in body:
                    return port
            except Exception:
                continue
        time.sleep(1.0)
    return None


def main() -> int:
    print("=== 1) 产物完整性 ===")
    check("exe 存在", os.path.isfile(EXE), EXE)
    internal = os.path.join(DIST, "_internal")
    static = os.path.join(internal, "web", "static", "index.html")
    check("前端静态资源已收集", os.path.isfile(static))
    check("前端 CSS 已收集",
          os.path.isfile(os.path.join(internal, "web", "static", "css", "app.css")))
    check("前端 JS 已收集",
          os.path.isfile(os.path.join(internal, "web", "static", "js", "app.js")))
    check("playwright node 驱动已收集",
          os.path.isfile(os.path.join(internal, "playwright", "driver", "node.exe")))
    check("pywin32 二进制已收集",
          os.path.isdir(os.path.join(internal, "pywin32_system32")))

    print("\n=== 2) 启动与自检 ===")
    proc = subprocess.Popen([EXE])
    port = find_service_port()
    check("exe 启动后服务可用", port is not None,
          "端口 %s" % port if port else "超时未探测到（进程存活=%s）"
          % (proc.poll() is None))

    if port:
        try:
            with _OPENER.open(
                    "http://127.0.0.1:%d/api/ping" % port, timeout=3) as r:
                body = r.read().decode("utf-8", "ignore")
            check("/api/ping 带 app 标识", '"app"' in body, body.strip())
        except Exception as exc:
            check("/api/ping 带 app 标识", False, str(exc))

        try:
            with _OPENER.open(
                    "http://127.0.0.1:%d/" % port, timeout=5) as r:
                html = r.read().decode("utf-8", "ignore")
            check("首页返回 HTML", "企业信用" in html, "长度 %d" % len(html))
        except Exception as exc:
            check("首页返回 HTML", False, str(exc))

        try:
            with _OPENER.open(
                    "http://127.0.0.1:%d/static/css/app.css" % port,
                    timeout=5) as r:
                css = r.read()
            check("CSS 可访问", len(css) > 500, "%d 字节" % len(css))
        except Exception as exc:
            check("CSS 可访问", False, str(exc))

        print("\n=== 3) 单实例 ===")
        p2 = subprocess.Popen([EXE])
        time.sleep(8)
        # 再启一个不该产生新端口
        ports = []
        for p in range(8760, 8840):
            try:
                with _OPENER.open(
                        "http://127.0.0.1:%d/api/ping" % p, timeout=0.6) as r:
                    if b'"app":"credit-shot"' in r.read().replace(b" ", b""):
                        ports.append(p)
            except Exception:
                continue
        check("重复启动未产生第二个服务", len(ports) == 1,
              "存活服务端口：%s" % ports)
        try:
            p2.wait(timeout=5)
        except Exception:
            p2.kill()

    print("\n=== 4) 数据目录 ===")
    appdata = os.environ.get("APPDATA")
    cred_dir = os.path.join(appdata, "企业信用截图工具") if appdata else ""
    check("凭据目录在 %APPDATA%（而非 exe 目录）",
          bool(cred_dir) and os.path.isdir(cred_dir), cred_dir)
    check("exe 目录内没有写凭据文件",
          not os.path.isfile(os.path.join(DIST, "凭据.ini")))

    # 收尾：关掉进程
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("   -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
