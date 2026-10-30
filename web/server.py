# -*- coding: utf-8 -*-
"""FastAPI 应用工厂。

只监听 127.0.0.1：这是本机工具，凭据和截图都在本机，
不对外网暴露端口是基本的安全要求。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web.api import router

__all__ = ["create_app", "serve", "find_free_port", "open_browser", "resource_dir"]

APP_NAME = "企业信用截图工具"
APP_VERSION = "2.2.9"

# 打包成 exe 后，静态资源被收集到 PyInstaller 的解包目录下（sys._MEIPASS），
# 而源码运行时它们就在 web/ 里。两种情况要分别取到正确的目录。
if getattr(sys, "frozen", False):
    # PyInstaller 把 web/static 收在 <解包根>/web/static
    BASE_DIR = os.path.join(getattr(sys, "_MEIPASS", ""), "web")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_DIR = os.path.join(BASE_DIR, "static")


def resource_dir() -> str:
    """资源根目录（供打包脚本与排错使用）。"""
    return BASE_DIR


def create_app() -> FastAPI:
    """构造 FastAPI 应用（挂路由 + 静态资源 + 首页）。"""
    app = FastAPI(
        title=APP_NAME,
        description="本地 Web 界面：控制浏览器自动化采集与截图。",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(router)

    if os.path.isdir(STATIC_DIR):

        class NoCacheStaticFiles(StaticFiles):
            """静态资源禁缓存：升级后浏览器必须拿最新 JS/CSS。

            Edge 的磁盘缓存对 127.0.0.1 一样生效 —— 升级版本后用户看到的
            还是旧界面逻辑（例如全选框行为没变），排查起来极其费劲。
            本程序静态资源很小，禁缓存没有任何性能代价。
            """

            def file_response(self, *args, **kwargs):
                resp = super().file_response(*args, **kwargs)
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                return resp

        app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR),
                  name="static")

    @app.get("/", include_in_schema=False)
    def index():
        """首页。"""
        page = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(page):
            return FileResponse(page)
        return {"detail": "前端资源缺失：%s" % STATIC_DIR}

    @app.get("/api/ping", include_in_schema=False)
    def ping():
        # app 字段用于识别「是不是本程序」——单实例检测靠它，
        # 避免把同端口上的其它服务误判成自己。
        return {"ok": True, "app": "credit-shot", "version": APP_VERSION}

    return app


def find_free_port(start: int = 8760, tries: int = 40) -> int:
    """找一个空闲端口（避免和用户已有服务冲突）。"""
    for port in range(start, start + tries):
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def open_browser(url: str) -> None:
    """用系统默认浏览器打开界面。

    这里刻意不用 webbrowser.open()，也不用 ShellExecuteW：
      两者都会让浏览器成为本程序的子进程（或经由 cmd 间接派生），
      打包成 windowed 程序后，浏览器启动完成的瞬间父进程会被连带结束，
      表现为「双击后浏览器开了，但程序立刻消失、服务也没了」。

    可靠做法：把 URL 交给 explorer.exe 进程去打开。
    explorer 是系统常驻进程，与本程序没有父子关系，
    浏览器由 explorer 派生，本程序不受影响。
    """
    def _open():
        try:
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
    # 独立线程 + 极短延迟：调用方（_wait_until_serving）已经确认端口真的
    # 能连上才会走到这里，不需要再白等 1.2 秒。
    threading.Timer(0.1, _open).start()


def _wait_until_serving(host: str, port: int, on_ready, url: str,
                        timeout: float = 90.0) -> None:
    """轮询直到端口真的能连上，然后调用 on_ready。

    为什么不用 uvicorn 的 startup 事件：
    那个事件在「应用 startup 钩子跑完」时触发，此时 socket 已 listen 但
    打包场景下资源解包、playwright 初始化还在前面，客户端仍可能连不上。
    实测打包版从启动到真正可连接要 12~14 秒。
    """
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                try:
                    on_ready(url)
                except Exception:
                    pass
                return
        except OSError:
            time.sleep(0.4)


def serve(host: str = "127.0.0.1", port: Optional[int] = None,
          open_ui: bool = True, on_ready=None) -> None:
    """启动本地服务（阻塞，直到服务结束）。

    on_ready：端口绑定成功后的回调，参数是访问地址。

    实现说明：
      * 不用 uvicorn.run()，而是手动建 Server 并监听 startup 事件，
        这样既能拿到「真的起来了」的确认，也能在打包环境下把异常抛给调用方
        （uvicorn.run 内部的异常在 windowed 模式会被丢弃，只剩「点了没反应」）。
      * 事件循环跑在**后台线程**，主线程只负责等待。
        打包成 windowed 程序后，主线程没有控制台，
        asyncio 在主线程的信号处理会被打断，表现为「服务刚起来就退出」。
    """
    import asyncio

    import uvicorn

    port = port or find_free_port()
    url = "http://%s:%d/" % (host, port)

    config = uvicorn.Config(create_app(), host=host, port=port,
                            log_level="warning")
    server = uvicorn.Server(config)

    async def _serve():
        # startup 事件在端口绑定成功后触发。
        # uvicorn 0.34 的 startup 签名是 startup(sockets=None)，要原样透传。
        original_startup = server.startup

        async def _startup(sockets=None):
            if original_startup is not None:
                await original_startup(sockets=sockets)

        server.startup = _startup
        await server.serve()

    def _run_loop():
        try:
            asyncio.run(_serve())
        except BaseException:
            import traceback
            try:
                traceback.print_exc()
            except Exception:
                pass

    # 后台线程跑事件循环
    loop_thread = threading.Thread(target=_run_loop, daemon=True,
                                    name="uvicorn-loop")
    loop_thread.start()

    # 轮询端口，直到真的能连上（uvicorn 的 startup 事件比实际可连接早若干秒，
    # 打包后解包 200MB 资源时更明显）。连上了才算「就绪」，此时再开浏览器。
    # 两个分支都必须走 _wait_until_serving：服务 <1s 就绪时，
    # 固定 3 秒定时器是纯白等（实测开界面白等 3~4 秒）。
    if on_ready is not None:
        def _ready(url):
            if open_ui:
                open_browser(url)
            on_ready(url)
        _wait_until_serving(host, port, _ready, url)
    elif open_ui:
        def _ready(url):
            open_browser(url)
        _wait_until_serving(host, port, _ready, url)

    # 主线程守活：等服务线程结束（或进程被结束）。
    # 用 Event 而不是 join 轮询：windowed 模式下主线程必须真正阻塞，
    # 否则 PyInstaller 的 bootloader 会在主线程返回时直接结束整个进程。
    stop_event = threading.Event()

    def _watch():
        # 事件循环线程一结束就通知主线程
        loop_thread.join()
        stop_event.set()

    threading.Thread(target=_watch, daemon=True, name="serve-watch").start()

    while not stop_event.is_set():
        stop_event.wait(0.5)
