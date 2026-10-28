# -*- coding: utf-8 -*-
"""企业信用一键截图工具 —— 程序入口（本地 Web 界面版）。

双击「启动.vbs」会经由 launcher.pyw 调到这里：
  1. 起一个只监听 127.0.0.1 的 FastAPI 服务；
  2. 自动用系统默认浏览器打开界面；
  3. 引擎跑在后台线程，界面通过 REST + SSE 与之交互。

为什么改成 Web 界面：
  * 界面层与引擎彻底解耦（引擎不认识 HTTP，Web 层不认识站点细节）；
  * 浏览器渲染，样式与排版能力远强于 tkinter 自绘；
  * 只监听本机，不对外暴露端口。
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _existing_service_port(start: int = 8760, tries: int = 80):
    """探测本机是否已有本服务在跑；返回端口号或 None。"""
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
                body = r.read()   # 只能读一次
            if b'"app":"credit-shot"' in body.replace(b" ", b""):
                return port
        except Exception:
            continue
    return None


def main() -> int:
    """启动本地服务。返回进程退出码。"""
    from web.server import serve

    # 单实例：已有实例在跑时只把它的界面推到前台，不再起第二个服务
    port = _existing_service_port()
    if port:
        url = "http://127.0.0.1:%d/" % port
        try:
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(["explorer.exe", url],
                             creationflags=flags, close_fds=True)
        except Exception:
            pass
        print("程序已在运行（端口 %d），已打开其界面。" % port)
        return 0

    print("企业信用一键截图工具 —— 本地 Web 界面")
    print("界面会在浏览器里自动打开；关闭本窗口即结束服务。")
    try:
        serve(host="127.0.0.1", open_ui=True)
    except KeyboardInterrupt:
        print("\n已退出。")
    except Exception as exc:
        print("启动失败：%s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
