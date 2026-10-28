# -*- coding: utf-8 -*-
"""构建一个「控制台版」exe，用来定位打包后的问题。

windowed 模式下看不到任何输出，出错时只能干瞪眼；
这个版本保留控制台，异常会直接打出来。

    python tools/build_debug_exe.py
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist_dbg")
BUILD = os.path.join(ROOT, "build_dbg")
ENTRY = os.path.join(ROOT, "app_entry.py")

HIDDEN = [
    "engine", "web.server", "web.api", "web.events",
    "core.browser", "core.capture", "core.page", "core.captcha",
    "core.yescaptcha", "core.subject", "core.control", "core.result",
    "core.errors", "auth.credentials", "auth.autologin",
    "platforms.base", "platforms.credit_china", "platforms.shixin",
    "platforms.ccgp", "platforms.mohurd", "platforms.plap",
    "platforms.gsxt", "platforms.wenshu",
]


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "调试版",
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        "--paths", ROOT,
        "--console",
        "--collect-all", "playwright",
        "--collect-all", "pywin32",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "fastapi",
        "--collect-submodules", "starlette",
    ]
    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    cmd += [
        "--add-data", os.path.join(ROOT, "web", "static") + ";web/static",
        ENTRY,
    ]
    print("构建控制台调试版…")
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
