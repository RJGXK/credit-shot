# -*- coding: utf-8 -*-
"""静态检查：找出各模块里「用到但没导入/没定义」的名字。

重构搬迁最容易出的错就是漏 import、漏参数，
这个脚本用 AST 扫一遍，比人工翻要快。
"""
from __future__ import annotations

import ast
import builtins
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


class Scope:
    """收集一个作用域里可见的名字。"""

    def __init__(self, parent=None):
        self.names = set()
        self.parent = parent

    def has(self, name: str) -> bool:
        scope = self
        while scope is not None:
            if name in scope.names:
                return True
            scope = scope.parent
        return False


def collect_targets(node, scope: Scope):
    """把赋值/导入/参数/函数定义的名字登记进作用域。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for a in child.names:
                scope.names.add((a.asname or a.name).split(".")[0])
        elif isinstance(child, ast.ImportFrom):
            for a in child.names:
                scope.names.add(a.asname or a.name)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.names.add(child.name)
        elif isinstance(child, ast.Assign):
            for t in child.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        scope.names.add(n.id)
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
            for n in ast.walk(child.target):
                if isinstance(n, ast.Name):
                    scope.names.add(n.id)
        elif isinstance(child, ast.arg):
            scope.names.add(child.arg)
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            for n in ast.walk(child.target):
                if isinstance(n, ast.Name):
                    scope.names.add(n.id)
        elif isinstance(child, ast.withitem):
            if child.optional_vars is not None:
                for n in ast.walk(child.optional_vars):
                    if isinstance(n, ast.Name):
                        scope.names.add(n.id)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            scope.names.add(child.name)
        elif isinstance(child, ast.comprehension):
            for n in ast.walk(child.target):
                if isinstance(n, ast.Name):
                    scope.names.add(n.id)


def check_file(path: str):
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, path)
    module_scope = Scope()
    collect_targets(tree, module_scope)

    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = Scope(module_scope)
        collect_targets(node, local)
        # 局部变量（赋值后才可见）也算已定义
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                local.names.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.names.add(sub.name)
            elif isinstance(sub, ast.arg):
                local.names.add(sub.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                name = sub.id
                if name in BUILTINS or local.has(name):
                    continue
                problems.append("%s:%d  %s -> 未定义的名字 %r"
                                % (os.path.basename(path), sub.lineno,
                                   node.name, name))
    return problems


def check_self_arg(path: str):
    """找出「实例方法漏写 self / cls」的地方。

    这类错在 Python 里不报语法错，只在**运行时**才炸成
    ``TypeError: Handler.foo() takes 1 positional argument but 2 were given``，
    静态检查完全看不出来（2026-10 就在裁判文书网和住建部上连踩三次）。

    判据：同一个类里，既有首参是 self/cls 的方法，又有首参不是 self/cls 的方法，
    且那个方法**没有** @staticmethod / @classmethod 装饰器 —— 几乎必然是漏写。
    """
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, path)
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [n for n in node.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        normal = [m for m in methods
                  if m.args.args and m.args.args[0].arg in ("self", "cls")]
        if not normal:
            continue
        for m in methods:
            if m in normal:
                continue
            # 有装饰器说明是刻意写成静态/类方法
            deco_names = set()
            for d in m.decorator_list:
                deco_names.add(ast.dump(d))
            if any("staticmethod" in d or "classmethod" in d for d in deco_names):
                continue
            args = m.args.args
            if not args:
                continue
            problems.append("%s:%d  %s.%s() 首参是 %r，疑似漏写 self"
                            % (os.path.basename(path), m.lineno,
                               node.name, m.name, args[0].arg))
    return problems


def check_ctrl_signal(path: str):
    """守卫「跳过此步」的两条命脉。

    1. **控制流异常必须继承 BaseException**：
       ``Aborted`` / ``Skipped`` 如果继承 ``Exception``，
       平台上几十处 ``except Exception:`` 会把「跳过」信号静默吃掉，
       用户点了【跳过此步】却什么都没发生（本项目踩过这个坑）。
    2. **平台层不准直接用 time.sleep**：
       固定等待必须走 ``self.engine.sleep()``，否则等待期间
       引擎听不见跳过/中止信号（响应会拖到整段等待结束）。
    """
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, path)
    base = os.path.basename(path)
    problems = []

    # --- 1) 控制流异常的继承关系 ---
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in ("Aborted", "Skipped"):
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
            if "BaseException" not in bases:
                problems.append("%s:%d  %s 必须继承 BaseException"
                                "（否则会被平台的 except Exception 吞掉，"
                                "【跳过此步】将静默失效）"
                                % (base, node.lineno, node.name))

    # --- 2) 平台层残留的 time.sleep ---
    if base.endswith(".py") and os.path.basename(os.path.dirname(path)) == "platforms":
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "sleep"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "time"):
                problems.append("%s:%d  平台层不该用 time.sleep"
                                "（等待期间听不见跳过/中止信号，请用 self.engine.sleep）"
                                % (base, node.lineno))
    return problems


def main():
    targets = []
    for folder in ("core", "platforms", "auth"):
        d = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(d)):
            if name.endswith(".py"):
                targets.append(os.path.join(d, name))
    targets.append(os.path.join(ROOT, "engine.py"))

    all_problems = []
    for path in targets:
        all_problems.extend(check_file(path))
        all_problems.extend(check_self_arg(path))
        all_problems.extend(check_ctrl_signal(path))
    if all_problems:
        print("发现 %d 个问题：" % len(all_problems))
        for p in all_problems:
            print("  " + p)
        return 1
    print("✔ %d 个模块静态检查通过"
              "（无未定义名字、无漏写 self、跳过信号链路完好）" % len(targets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
