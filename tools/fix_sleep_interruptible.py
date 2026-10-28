# -*- coding: utf-8 -*-
"""把平台层（platforms/*.py）的固定等待改成可中断等待。

背景：用户点【跳过此步】后引擎听不见 —— 因为平台层全部用 ``time.sleep``，
必须等整段睡完才会回到引擎的检查点。改成 ``self.engine.sleep(x)`` 后，
等待每 0.2 秒检查一次信号，最迟 0.2 秒响应。

只替换 handler 实例方法体内的 time.sleep（那些地方 self 可用）；
模块级函数里的不动。
"""
import ast
import io
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["ccgp.py", "credit_china.py", "gsxt.py", "mohurd.py",
         "plap.py", "shixin.py", "wenshu.py"]


def handler_line_ranges(path):
    """返回可以直接替换 time.sleep 的行号集合（handler 实例方法体内）。"""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = [a.arg for a in node.args.args]
        if not args or args[0] not in ("self",):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "sleep"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "time"):
                lines.add(sub.lineno)
    return lines


def main():
    total = 0
    for name in FILES:
        path = os.path.join(BASE, "platforms", name)
        targets = handler_line_ranges(path)
        if not targets:
            continue
        src = open(path, encoding="utf-8").read().splitlines(True)
        changed = 0
        for idx, line in enumerate(src):
            lineno = idx + 1
            if lineno not in targets:
                continue
            new = re.sub(r"\btime\.sleep\(", "self.engine.sleep(", line)
            if new != line:
                src[idx] = new
                changed += 1
        if changed:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write("".join(src))
            print("%-22s 替换 %2d 处" % (name, changed))
            total += changed
    print("合计替换 %d 处" % total)


if __name__ == "__main__":
    main()
