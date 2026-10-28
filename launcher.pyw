# -*- coding: utf-8 -*-
"""无控制台窗口的启动入口（由 pythonw.exe / 启动.vbs 调用）。

与 `python main.py` 的区别：
  * 不弹黑色控制台窗口；
  * stdout / stderr 全部丢到 devnull（pythonw 下它们是 None，任何 print 都会崩）；
  * 未捕获的异常写入 `启动错误.log`，并在桌面上弹窗提示。

依赖缺失时（playwright / pillow）会尝试静默安装，安装过程不弹控制台。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

ERROR_LOG = os.path.join(BASE, "启动错误.log")

# pythonw.exe 下 sys.stdout / sys.stderr 是 None，这里统一替换成 devnull
try:
    _devnull = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = _devnull
    sys.stderr = _devnull
except Exception:
    pass


def _write_log(text: str):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("---- %s ----\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    """把 tkinter 回调里的异常也落盘（否则 pythonw 下会静默消失）。"""
    _write_log("".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _excepthook


def _popup(title: str, msg: str, icon: int = 16):
    try:
        import tkinter.messagebox as mb
        mb.showerror(title, msg)
    except Exception:
        pass


def _ensure_deps() -> bool:
    """检查 playwright / pillow / fastapi / uvicorn，缺失则静默安装。"""
    try:
        import playwright  # noqa: F401
        from PIL import Image  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except Exception:
        pass
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "playwright", "pillow", "fastapi", "uvicorn"],
                       creationflags=flags, check=False)
        import playwright  # noqa: F401
        from PIL import Image  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except Exception as exc:
        _write_log("依赖安装失败：%s" % exc)
        _popup("缺少运行依赖",
               "未能安装 playwright / pillow / fastapi / uvicorn。\n\n"
               "请双击同目录下的「启动.bat」手动安装依赖，或执行：\n"
               "    pip install playwright pillow fastapi uvicorn")
        return False


def main():
    if not _ensure_deps():
        return
    from main import main as run_gui
    run_gui()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _write_log(traceback.format_exc())
        _popup("启动失败", "程序启动出错，详情见：\n%s" % ERROR_LOG)
