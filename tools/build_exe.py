# -*- coding: utf-8 -*-
"""用 PyInstaller 构建 Windows 可执行程序。

    python tools/build_exe.py

产物：
    dist/企业信用截图工具/企业信用截图工具.exe   （onedir，启动快、易调试）
    dist/企业信用截图工具.exe                     （onefile，单文件、启动稍慢）

打包要点（踩过的坑都在这）：
  1. playwright 的 node 驱动（driver/node.exe + driver/package）必须整个收进去，
     否则浏览器起不来 —— 用 collect_all("playwright")。
  2. pywin32 的 win32api / win32gui / win32process 是二进制扩展，
     PyInstaller 没有内置 hook，用 collect_all("pywin32") 兜住。
  3. 前端的 html/css/js 不是 Python 模块，必须用 add_data 收进 web/static。
  4. uvicorn 的日志/协议实现是动态导入的，用 collect_submodules 收干净。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
ENTRY = os.path.join(ROOT, "app_entry.py")
ICON = os.path.join(ROOT, "assets", "app.ico")

APP_NAME = "企业信用截图工具"


def _sep() -> str:
    return ";" if os.name == "nt" else ":"


def build(onefile: bool = False) -> int:
    """执行打包。返回退出码。"""
    if not os.path.exists(ENTRY):
        print("找不到入口文件：%s" % ENTRY)
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        "--paths", ROOT,
        # GUI 模式：不出控制台窗口
        "--windowed",
        # 收集 playwright（含 90MB 的 node 驱动）
        "--collect-all", "playwright",
        # 收集 pywin32 的二进制扩展
        "--collect-all", "pywin32",
        # pywebview（软件窗口外壳）：它按后端动态导入 dll，必须整个收进去
        "--collect-all", "webview",
        "--collect-all", "pywebview",
        # 收集 uvicorn 的动态导入子模块
        "--collect-submodules", "uvicorn",
        # 收集 FastAPI / Starlette / pydantic 的动态部分
        "--collect-submodules", "fastapi",
        "--collect-submodules", "starlette",
        # 隐藏导入：这些模块是动态加载的，分析器扫不到
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "engine",
        "--hidden-import", "web.server",
        "--hidden-import", "web.api",
        "--hidden-import", "web.events",
        "--hidden-import", "desktop_window",
        "--hidden-import", "core.browser",
        "--hidden-import", "core.capture",
        "--hidden-import", "core.page",
        "--hidden-import", "core.captcha",
        "--hidden-import", "core.yescaptcha",
        "--hidden-import", "core.subject",
        "--hidden-import", "core.control",
        "--hidden-import", "core.result",
        "--hidden-import", "core.errors",
        "--hidden-import", "auth.credentials",
        "--hidden-import", "auth.autologin",
        "--hidden-import", "platforms.base",
        "--hidden-import", "platforms.credit_china",
        "--hidden-import", "platforms.shixin",
        "--hidden-import", "platforms.ccgp",
        "--hidden-import", "platforms.mohurd",
        "--hidden-import", "platforms.plap",
        "--hidden-import", "platforms.gsxt",
        "--hidden-import", "platforms.wenshu",
        "--hidden-import", "platforms.cnca",
        # 平台包整包收一遍：以后新增平台不用改这里（漏一个就是运行期
        # 「找不到处理器」才炸，不如每次全收）
        "--collect-submodules", "platforms",
        # 前端静态资源：收集到 <解包根>/web/static，代码里按这个路径找。
        # 注意：--add-data 的源路径是相对 spec 文件所在目录解析的，
        # 而 spec 放在 build/ 下，所以必须用绝对路径，否则会报
        # 「Unable to find ... when adding binary and data files」，
        # 结果是静态资源压根没进包（启动后首页报「前端资源缺失」）。
        "--add-data", os.path.join(ROOT, "web", "static") + _sep() + "web/static",
        # 使用说明也带一份，方便用户查阅
        "--add-data", os.path.join(ROOT, "使用说明.md") + _sep() + ".",
    ]

    if os.path.exists(ICON):
        cmd += ["--icon", ICON]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append(ENTRY)

    print("执行：%s\n" % " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    return rc


def main() -> int:
    onefile = "--onefile" in sys.argv
    rc = build(onefile=onefile)
    if rc != 0:
        print("\n打包失败，退出码 %d" % rc)
        return rc

    exe = os.path.join(DIST, APP_NAME, APP_NAME + ".exe")
    if onefile:
        exe = os.path.join(DIST, APP_NAME + ".exe")
    if os.path.exists(exe):
        size = os.path.getsize(exe) / 1024 / 1024
        print("\n✔ 打包完成：%s（%.1f MB）" % (exe, size))
    else:
        print("\n⚠ 未找到预期产物，请检查 dist/ 目录")
        rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
