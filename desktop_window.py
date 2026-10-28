# -*- coding: utf-8 -*-
"""桌面窗口外壳 —— 把 Web 界面装进独立的应用窗口。

为什么要有这一层：
  安装版是给最终用户用的，双击后应该弹出「软件窗口」，
  而不是跳到系统浏览器里开网页（浏览器有地址栏、标签页、书签，
  看起来像在用一个网站，而不是一个软件）。

实现：pywebview（底层是系统自带的 Edge WebView2，Windows 10/11 自带，
不需要用户额外安装）。后端服务照旧跑在 127.0.0.1，只是「谁去显示它」变了：
  * 原来：explorer.exe <url> → 打开外部浏览器
  * 现在：pywebview 建一个原生窗口 → 加载同一个 url

窗口关闭时结束服务进程，避免留下后台孤儿。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

__all__ = ["open_window", "has_pywebview", "open_in_external_browser"]

APP_TITLE = "企业信用一键截图工具"
APP_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "app.ico")


def has_pywebview() -> bool:
    """pywebview 是否可用（打包后可能没收进去）。"""
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def open_in_external_browser(url: str) -> bool:
    """用系统默认浏览器打开界面（界面上的「用浏览器打开」按钮用）。

    关键点：必须交给 explorer.exe，不能用 webbrowser.open() ——
    后者会让浏览器成为本程序的子进程，浏览器一启动完父进程就被连带结束。
    """
    try:
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["explorer.exe", url],
                         creationflags=flags, close_fds=True)
        return True
    except Exception:
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False


def _window_chrome() -> tuple:
    """窗口边框（标题栏 + 左右边框）在**逻辑像素**上占多少。

    实测（135% 缩放的本机）：
      传 width=1180  → 网页 innerWidth = 1080（差 100）
      传 height=860  → 网页 innerHeight = 762（差 98）
    注意 pywebview 的 width/height 已经是逻辑像素，再乘 DPR 会过头。

    这里再补一点余量（+10/+32），确保视口不比设计尺寸小 ——
    视口小一点，底部的工具栏就可能被顶出可视区。
    """
    return 110, 130


def _screen_size():
    """主显示器的物理像素尺寸（失败时返回 (0, 0)）。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        return int(w), int(h)
    except Exception:
        return 0, 0


def _display_scale() -> float:
    """当前显示器的缩放比例（DPR）。

    为什么需要它：
      pywebview 的 width/height 是**逻辑像素**，而屏幕尺寸是物理像素，
      两者要靠缩放比例换算。

    注意坑：`GetDpiForSystem()` 在本机返回 96（scale=1.0），
    但 WebView2 实际用的是 135%（DPR=1.35）—— 两者不一致。
    所以优先用「进程感知到的 DPI」（DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2），
    它才是真正决定窗口缩放的那个值。
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        try:
            ctx = user32.GetThreadDpiAwarenessContext()
            dpi = user32.GetDpiForWindow(ctx) if ctx else 0
        except Exception:
            dpi = 0
        if not dpi:
            dpi = user32.GetDpiForSystem()
        if dpi and dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _work_area():
    """屏幕工作区尺寸（物理像素，已排除任务栏）。"""
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("l", wintypes.LONG), ("t", wintypes.LONG),
                        ("r", wintypes.LONG), ("b", wintypes.LONG)]

        rect = RECT()
        # SPI_GETWORKAREA = 0x0030
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0030, 0, ctypes.byref(rect), 0)
        if ok and rect.r > rect.l and rect.b > rect.t:
            return rect.r - rect.l, rect.b - rect.t
    except Exception:
        pass
    return _screen_size()


def open_window(url: str, title: str = APP_TITLE, width: int = 1180,
                height: int = 860, min_width: int = 980,
                min_height: int = 640) -> None:
    """在独立的应用窗口里显示界面（阻塞，直到窗口关闭）。

    窗口关闭 → 服务进程随之结束（由调用方注册的清理逻辑负责）。
    """
    import inspect

    import webview

    # pywebview 的 width/height 就是逻辑像素；只需补上窗口边框占掉的部分，
    # 让网页视口正好等于设计尺寸（不要再乘 DPR，会过头）。
    chrome_w, chrome_h = _window_chrome()
    phys_w = int(width) + chrome_w
    phys_h = int(height) + chrome_h
    phys_min_w = int(min_width) + chrome_w
    phys_min_h = int(min_height) + chrome_h

    # 别超过屏幕工作区（已排除任务栏），否则窗口会大到「一部分在屏幕外」。
    # 工作区是物理像素，要按缩放换算成逻辑像素再比较。
    wa_w, wa_h = _work_area()
    scale = _display_scale()
    if wa_w > 0:
        max_w = int(wa_w / scale * 0.95) - chrome_w
        max_h = int(wa_h / scale * 0.95) - chrome_h
        phys_w = min(phys_w, max_w)
        phys_h = min(phys_h, max_h)
    phys_min_w = min(phys_min_w, phys_w)
    phys_min_h = min(phys_min_h, phys_h)

    # pywebview 各版本参数有出入（新版去掉了 icon），按实际签名构造
    kwargs = {
        "width": phys_w,
        "height": phys_h,
        "min_size": (phys_min_w, phys_min_h),
        "frameless": False,
        "easy_drag": False,
        "text_select": True,     # 允许选中复制界面里的文字
        "background_color": "#F2F5FA",
    }
    try:
        supported = set(inspect.signature(webview.create_window).parameters)
    except (TypeError, ValueError):
        supported = set()
    kwargs = {k: v for k, v in kwargs.items() if not supported or k in supported}

    window = webview.create_window(title, url, **kwargs)

    # 窗口关闭后结束主流程（pywebview 的 start() 会返回）
    def _on_closed():
        try:
            _request_shutdown()
        except Exception:
            pass

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    webview.start(debug=False)


def _request_shutdown() -> None:
    """请求主流程退出（供 window.events.closed 回调调用）。"""
    shutdown = getattr(_request_shutdown, "_hook", None)
    if callable(shutdown):
        shutdown()


def set_shutdown_hook(func) -> None:
    """注册「窗口关闭时该做什么」的回调。"""
    _request_shutdown._hook = func


def run_with_window(url: str, serve_func, title: str = APP_TITLE) -> int:
    """完整流程：起服务 → 开窗口 → 窗口关闭则结束服务。

    serve_func：形如 serve(host=..., port=..., open_ui=False) 的可调用对象，
                必须在**后台线程**里跑（pywebview 需要主线程跑消息循环）。

    返回进程退出码。
    """
    # 1) 后台线程起服务
    service_error = []

    def _serve():
        try:
            serve_func()
        except BaseException as exc:            # noqa: BLE001
            service_error.append(exc)

    thread = threading.Thread(target=_serve, daemon=True, name="local-service")
    thread.start()

    # 2) 等服务真正就绪（端口能连上）
    if not _wait_for_service(url):
        if service_error:
            print("启动失败：%s" % service_error[0])
            return 1
        print("服务启动超时。")
        return 1

    # 3) 窗口关闭 → 结束服务线程（daemon 线程随主进程退出）
    set_shutdown_hook(lambda: None)

    # 4) 开窗口（阻塞）
    try:
        open_window(url, title=title)
    except Exception as exc:
        print("窗口打开失败：%s" % exc)
        return 1
    return 0


def _wait_for_service(url: str, timeout: float = 90.0) -> bool:
    """等本地服务真的能连上。"""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.4)
    return False
