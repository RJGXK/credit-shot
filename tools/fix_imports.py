# -*- coding: utf-8 -*-
"""一次性补丁：给搬迁后的平台模块补齐 import，并修正 core/capture.py 的残留。

engine.py 已被换成编排器，tools/split_engine.py 不再可重复执行，
这个脚本承担「搬迁收尾」的职责。
"""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 平台模块统一需要的 import
COMMON_IMPORTS = [
    "from config import HOME_URLS, MODE_PERSON",
    "from core.errors import Aborted, EngineError, Skipped",
    "from core.result import StepResult",
    "from core.subject import safe_name",
    "from typing import List",
]


def patch_platform(path: str) -> bool:
    src = io.open(path, encoding="utf-8").read()
    if "from core.result import StepResult" in src:
        return False
    # 插到 "from platforms.base import PlatformHandler" 之前
    marker = "from platforms.base import PlatformHandler"
    if marker not in src:
        raise SystemExit("%s 里找不到插入点" % path)
    block = "\n".join(COMMON_IMPORTS) + "\n"
    src = src.replace(marker, block + marker, 1)
    # mohurd 还会用 dismiss_site_dialogs
    if "dismiss_site_dialogs" in src and "from core.capture import" not in src:
        src = src.replace(marker, "from core.capture import dismiss_site_dialogs\n" + marker, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    return True


def patch_capture(path: str) -> bool:
    """把「从 self 上取当前主体」的残留改成用形参 subject。"""
    src = io.open(path, encoding="utf-8").read()
    old = '''    subj = getattr(self, "_current_subject", None)
    unit = company
    if subj and subj.mode == MODE_PERSON:
        unit = "%s（身份证号：%s）" % (subj.person or "-", subj.idcard or "-")
'''
    new = '''    unit = unit_label_for_bar(company, subject)
'''
    if old not in src:
        return False
    src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    return True


def main():
    changed = []
    for name in sorted(os.listdir(os.path.join(ROOT, "platforms"))):
        if name.endswith(".py") and name not in ("__init__.py", "base.py"):
            path = os.path.join(ROOT, "platforms", name)
            if patch_platform(path):
                changed.append("platforms/" + name)
    if patch_capture(os.path.join(ROOT, "core", "capture.py")):
        changed.append("core/capture.py")
    print("已修补：%s" % ("、".join(changed) if changed else "（无）"))


if __name__ == "__main__":
    main()
