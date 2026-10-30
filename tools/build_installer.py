# -*- coding: utf-8 -*-
"""编译 NSIS 安装包。

    python tools/build_installer.py

产物：dist\\企业信用一键截图工具_安装包.exe

为什么要用 Python 调 makensis：
  在 Git Bash 里直接跑 makensis，/DAPP_VERSION=2.0.0 会被当成路径转换
  （变成 D:/WorkBuddy/.../DAPP_VERSION=2.0.0），脚本就找不到文件了。
  用 subprocess 传列表参数可以绕开 shell 的路径改写。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NSIS_CANDIDATES = [
    r"C:\Program Files (x86)\NSIS\makensis.exe",
    r"C:\Program Files\NSIS\makensis.exe",
]
VERSION = "2.1.8"


def find_makensis() -> str:
    """定位 makensis.exe。"""
    for p in NSIS_CANDIDATES:
        if os.path.isfile(p):
            return p
    found = shutil.which("makensis")
    if found:
        return found
    return ""


def main() -> int:
    makensis = find_makensis()
    if not makensis:
        print("未找到 NSIS 的 makensis.exe。")
        print("请安装 NSIS：https://nsis.sourceforge.io/Download")
        print("装好后重跑本脚本。")
        return 1

    script = os.path.join(ROOT, "installer.nsi")
    if not os.path.isfile(script):
        print("找不到安装脚本：%s" % script)
        return 1

    # 前置检查：exe 产物必须已存在
    exe = os.path.join(ROOT, "dist", "企业信用截图工具", "企业信用截图工具.exe")
    if not os.path.isfile(exe):
        print("找不到打包产物：%s" % exe)
        print("请先运行：python tools/build_exe.py")
        return 1

    cmd = [makensis, "/DAPP_VERSION=%s" % VERSION, script]
    print("执行：%s\n" % " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        print("\n安装包编译失败，退出码 %d" % rc)
        return rc

    out = os.path.join(ROOT, "dist", "企业信用一键截图工具_安装包.exe")
    if os.path.isfile(out):
        print("\n✔ 安装包已生成：%s（%.1f MB）"
              % (out, os.path.getsize(out) / 1024 / 1024))
        return 0
    print("\n⚠ 未找到预期产物，请检查 dist/ 目录")
    return 2


if __name__ == "__main__":
    sys.exit(main())
