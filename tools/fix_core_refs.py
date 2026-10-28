# -*- coding: utf-8 -*-
"""搬迁收尾：修正 core/ 三个模块里「self 归属」被改错的地方。

搬迁脚本把 Engine 的 self.xxx 统一重写成了 self.engine.xxx，
但 core 模块本身不是 Engine 的子类，这些引用要改回模块自己的成员。
"""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fix_browser():
    path = os.path.join(ROOT, "core", "browser.py")
    s = io.open(path, encoding="utf-8").read()
    s = s.replace("self.engine.log", "self.log")
    s = s.replace("self.engine.timeout", "self.timeout")
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("✔ core/browser.py")


def fix_captcha():
    path = os.path.join(ROOT, "core", "captcha.py")
    s = io.open(path, encoding="utf-8").read()
    # 客户端改为直接用模块顶部的 YesCaptcha
    s = s.replace("""                import captcha as _captcha_mod
                self._client = _captcha_mod.YesCaptcha(
                    self.api_key, self.region, log)""",
                  """                self._client = YesCaptcha(
                    self.api_key, self.region, self.log)""")
    s = s.replace("solver = client()", "solver = self.client()")
    # 类方法里的日志调用要带 self
    s = re.sub(r"(?<![\w.])log\(", "self.log(", s)
    s = s.replace("self.self.log(", "self.log(")
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("✔ core/captcha.py")


def fix_capture():
    path = os.path.join(ROOT, "core", "capture.py")
    s = io.open(path, encoding="utf-8").read()
    s = s.replace("def insert_info_bar(page, company: str, step: dict, subject=None) -> None:",
                  "def insert_info_bar(page, company: str, step: dict, subject=None,\n"
                  "                     log=print) -> None:")
    s = s.replace("def shot_element_by_title(page, path: str, title: str) -> bool:",
                  "def shot_element_by_title(page, path: str, title: str,\n"
                  "                           log=print) -> bool:")
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("✔ core/capture.py")


def main():
    fix_browser()
    fix_captcha()
    fix_capture()


if __name__ == "__main__":
    main()
