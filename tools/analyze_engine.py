# -*- coding: utf-8 -*-
"""重构辅助：分析 engine.py 的方法归属与跨模块调用。

只读，不改任何东西。输出：
  1) 每个方法属于哪个「平台组」
  2) 平台组之间的交叉调用（决定拆包后要不要改调用点）
"""
import ast
import io
import os
import sys
from collections import defaultdict

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine.py")

# 方法名前缀 -> 平台组
PREFIX_GROUP = [
    ("_ws_", "wenshu"),
    ("_mohurd_", "mohurd"),
    ("_plap_", "plap"),
    ("_gsxt_", "gsxt"),
    ("_cc_", "credit_china"),
    ("_step_creditchina", "credit_china"),
    ("_step_zxgk", "shixin"),
    ("_step_ccgp", "ccgp"),
]


def group_of(name: str) -> str:
    for prefix, group in PREFIX_GROUP:
        if name.startswith(prefix):
            return group
    return "engine"


def main():
    src = io.open(ENGINE, encoding="utf-8").read()
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Engine")

    methods = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[node.name] = node

    by_group = defaultdict(list)
    for name in methods:
        by_group[group_of(name)].append(name)

    print("=== 方法按组统计（共 %d 个方法）===" % len(methods))
    for group in sorted(by_group, key=lambda g: -len(by_group[g])):
        names = sorted(by_group[group])
        print("\n[%s] %d 个" % (group, len(names)))
        for n in names:
            # 每个方法体多少行
            end = getattr(methods[n], "end_lineno", methods[n].lineno)
            print("   %-34s %4d 行" % (n, end - methods[n].lineno + 1))

    # 交叉调用分析
    print("\n=== 跨组调用 ===")
    cross = defaultdict(lambda: defaultdict(int))
    for name, node in methods.items():
        src_group = group_of(name)
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "self"):
                callee = sub.func.attr
                if callee not in methods:
                    continue
                dst = group_of(callee)
                if dst != src_group:
                    cross[(src_group, dst)][callee] += 1
    if not cross:
        print("（无跨组调用，拆分零风险）")
    for (src_g, dst_g), calls in sorted(cross.items()):
        total = sum(calls.values())
        print("\n%s -> %s （%d 处）" % (src_g, dst_g, total))
        for c, n in sorted(calls.items(), key=lambda kv: -kv[1]):
            print("    %-32s x%d" % (c, n))


if __name__ == "__main__":
    main()
