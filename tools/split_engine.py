# -*- coding: utf-8 -*-
"""重构工具：把 engine.py 这个上帝类按职责拆成 core/ + platforms/。

设计原则：**机械搬迁，逻辑零改动**。
  * 方法体逐字保留，只改「self.<属性>」的归属指向；
  * 任何没登记在映射表里的 self.xxx 都会报错退出，不允许静默漏改；
  * 两阶段执行：先 `--stage modules` 生成新模块（不动 engine.py），
    再 `--stage engine` 切换 engine.py 为编排器。

用法：
    python tools/split_engine.py --stage modules
    python tools/split_engine.py --stage engine
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PATH = os.path.join(ROOT, "engine.py")

# ================================================================ 方法分组
BROWSER_METHODS = [
    "_free_port", "_find_exe", "_open_browser", "_port_file", "_probe_cdp",
    "_read_reusable_port", "_kill_stale_browsers", "_close_browser", "_connect_cdp",
]
PAGE_METHODS = [
    "_fill_controlled", "_set_native", "_click_by_text", "_wait_text",
    "_wait_ready", "_eval_retry",
]
CAPTURE_METHODS = [
    "_info_bar", "_remove_info_bar", "_unstick_page", "_restick_page",
    "_shot_element_by_title", "_capture", "_compose_date_panel",
    "_dismiss_site_dialogs",
]
CAPTCHA_METHODS = ["_solver", "_solve_image_vcode", "_solve_frame_vcode",
                   "_solve_recaptcha"]

PLATFORM_METHODS = OrderedDict([
    ("credit_china", ["_step_creditchina", "_step_creditchina_person", "_cc_state"]),
    ("shixin", ["_step_zxgk"]),
    ("ccgp", ["_step_ccgp"]),
    ("mohurd", ["_group_mohurd", "_mohurd_search", "_mohurd_wait_stable", "_mohurd_open_detail",
                "_mohurd_click_detail_once", "_mohurd_ensure_data",
                "_mohurd_switch_tab", "_mohurd_tab_active", "_mohurd_wait_table",
                "_mohurd_state"]),
    ("plap", ["_group_plap", "_plap_prepare", "_plap_switch_and_query", "_plap_fill_field",
              "_plap_fill_keyword", "_plap_select_type", "_plap_state"]),
    ("gsxt", ["_group_gsxt_detail", "_gsxt_open", "_gsxt_wait_keyword", "_gsxt_enter_detail",
              "_step_gsxt_basic", "_gsxt_click_left", "_step_gsxt_section",
              "_step_gsxt_blacklist"]),
    ("wenshu", ["_ws_conditions", "_ws_open_advanced", "_ws_search",
                "_ws_refine_by_fulltext", "_ws_do_search", "_ws_wait_ready",
                "_ws_ensure_login", "_ws_alias_names", "_group_wenshu",
                "_ws_person_shared", "_ws_run_step", "_ws_log_state", "_ws_state"]),
])

ENGINE_KEEP = [
    "__init__", "_pace", "_check_stop", "_wait_manual", "_auto_login",
    "_run_single_step", "_shot_step", "run", "_run_group", "_run_one",
    "self_check",
]

# 类级常量（各平台的状态判定脚本），随平台一起搬
CLASS_CONSTANTS = {
    "CC_STATE_JS": "credit_china",
    "ZX_STATE_JS": "shixin",
    "MOHURD_STATE_JS": "mohurd",
    "PLAP_STATE_JS": "plap",
    "WS_HOME": "wenshu",
    "WS_ADV_CLS": "wenshu",
    "WS_STATE_JS": "wenshu",
    "WS_FILL_JS": "wenshu",
}

# ================================================================ 名字映射
# 旧名 -> (新名, 归属)
#   core_page / core_capture → 对应模块的模块级函数
#   captcha                  → CaptchaSolver 对象上的方法
#   self                     → 平台 handler 自己的方法
#   engine                   → Engine 实例上的方法/属性
RENAME = {
    "_fill_controlled": ("fill_controlled", "core_page"),
    "_set_native": ("set_native", "core_page"),
    "_click_by_text": ("click_by_text", "core_page"),
    "_wait_text": ("wait_text", "core_page"),
    "_wait_ready": ("wait_ready", "core_page"),
    "_eval_retry": ("eval_retry", "core_page"),
    "_info_bar": ("insert_info_bar", "core_capture"),
    "_remove_info_bar": ("remove_info_bar", "core_capture"),
    "_unstick_page": ("unstick_page", "core_capture"),
    "_restick_page": ("restick_page", "core_capture"),
    "_shot_element_by_title": ("shot_element_by_title", "core_capture"),
    "_capture": ("capture", "core_capture"),
    "_compose_date_panel": ("compose_date_panel", "core_capture"),
    "_dismiss_site_dialogs": ("dismiss_site_dialogs", "core_capture"),
    "_solver": ("captcha_solver", "engine"),
    "_solve_image_vcode": ("solve_image_captcha", "captcha"),
    "_solve_frame_vcode": ("solve_frame_captcha", "captcha"),
    "_solve_recaptcha": ("solve_recaptcha", "captcha"),
    "_pace": ("pace", "engine"),
    "_check_stop": ("check_stop", "engine"),
    "_wait_manual": ("wait_manual", "engine"),
    "_auto_login": ("auto_login", "engine"),
    "_shot_step": ("shot_step", "engine"),
    "_current_subject": ("current_subject", "engine"),
    "_gsxt_in_detail": ("gsxt_in_detail", "engine"),
    "_vcode_ok": ("vcode_ok", "engine"),
    "log": ("log", "engine"),
    "control": ("control", "engine"),
    "output_dir": ("output_dir", "engine"),
    "timeout": ("timeout", "engine"),
    "shot_mode": ("shot_mode", "engine"),
    "ctx": ("ctx", "engine"),
    "browser": ("browser", "engine"),
    "_mohurd_company": ("_mohurd_company", "self"),
}

# core/browser.py 内部：旧 self.xxx -> 新 self.xxx
PAGE_MAP = {"_check_stop": ("check_stop", "bare")}

BROWSER_MAP = {
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "ctx": ("ctx", "self"),
    "browser": ("kind", "self"), "_proc": ("proc", "self"), "_pw": ("pw", "self"),
    "_browser": ("browser_obj", "self"),
    "_free_port": ("free_port", "self"), "_find_exe": ("find_exe", "self"),
    "_read_reusable_port": ("read_reusable_port", "self"),
    "_connect_cdp": ("connect_cdp", "self"),
    "_probe_cdp": ("probe_cdp", "self"),
    "_kill_stale_browsers": ("kill_stale_browsers", "self"),
    "_port_file": ("port_file", "self"),
}
# core/capture.py 内部
CAPTURE_MAP = {
    "_current_subject": ("subject", "bare"), "shot_mode": ("shot_mode", "bare"),
    "log": ("log", "bare"),
    "_dismiss_site_dialogs": ("dismiss_site_dialogs", "fn"),
    "_info_bar": ("insert_info_bar", "fn"),
    "_unstick_page": ("unstick_page", "fn"),
    "_restick_page": ("restick_page", "fn"),
    "_shot_element_by_title": ("shot_element_by_title", "fn"),
    "_remove_info_bar": ("remove_info_bar", "fn"),
    "_compose_date_panel": ("compose_date_panel", "fn"),
    "_click_by_text": ("click_by_text", "fn"),
}
# core/captcha.py 内部
CAPTCHA_MAP = {
    "_solver": ("client", "bare"), "log": ("log", "bare"),
    "_click_by_text": ("click_by_text", "fn"),
    "captcha_key": ("api_key", "self"), "captcha_region": ("region", "self"),
    "_captcha": ("_client", "self"),
}

PLATFORM_RENAME = {
    "_step_creditchina": "collect_list",
    "_step_creditchina_person": "collect_person_list",
    "_cc_state": "read_state",
    "_step_zxgk": "collect_dishonest",
    "_step_ccgp": "collect",
    "_mohurd_search": "search",
    "_mohurd_wait_stable": "wait_stable",
    "_mohurd_open_detail": "open_detail",
    "_mohurd_click_detail_once": "click_detail_once",
    "_mohurd_ensure_data": "ensure_data",
    "_mohurd_switch_tab": "switch_tab",
    "_mohurd_tab_active": "tab_active",
    "_mohurd_wait_table": "wait_table",
    "_mohurd_state": "read_state",
    "_plap_prepare": "prepare",
    "_plap_switch_and_query": "switch_and_query",
    "_plap_fill_field": "fill_field",
    "_plap_fill_keyword": "fill_keyword",
    "_plap_select_type": "select_type",
    "_plap_state": "read_state",
    "_gsxt_open": "open_portal",
    "_gsxt_wait_keyword": "wait_keyword",
    "_gsxt_enter_detail": "enter_detail",
    "_step_gsxt_basic": "collect_basic",
    "_gsxt_click_left": "click_left_nav",
    "_step_gsxt_section": "collect_section",
    "_step_gsxt_blacklist": "collect_blacklist",
    "_ws_conditions": "build_conditions",
    "_ws_open_advanced": "open_advanced_search",
    "_ws_search": "search",
    "_ws_refine_by_fulltext": "refine_by_fulltext",
    "_ws_do_search": "do_search",
    "_ws_wait_ready": "wait_ready",
    "_ws_ensure_login": "ensure_login",
    "_ws_alias_names": "read_alias_names",
    "_group_wenshu": "collect_group",
    "_ws_person_shared": "collect_person_group",
    "_ws_run_step": "run_step",
    "_ws_log_state": "log_state",
    "_group_mohurd": "collect_group",
    "_group_plap": "collect_group",
    "_group_gsxt_detail": "collect_group",
    "_ws_state": "read_state",
}

PLATFORM_TITLES = {
    "credit_china": ("信用中国", "credit_china.py",
                     "信用中国（信息公示 + 专项查询）：严重失信主体名单、经营异常名录、"
                     "安全生产严重失信（法人/自然人）、重大税收违法等。"),
    "shixin": ("失信被执行人", "shixin.py",
               "最高法失信被执行人查询（zxgk.court.gov.cn）：单位与人员两种口径。"),
    "ccgp": ("中国政府采购网", "ccgp.py",
             "中国政府采购网：政府采购严重违法失信行为记录名单（必须从首页进入）。"),
    "mohurd": ("住建部", "mohurd.py",
               "住房和城乡建设部：企业资质资格、不良行为、黑名单记录、失信联合惩戒记录。"),
    "plap": ("军队采购网", "plap.py",
             "军队采购网：全部/预警/暂停/失信/政府采购失信五类名单（单位 + 专家个人）。"),
    "gsxt": ("国家企业信用信息公示系统", "gsxt.py",
             "国家企业信用信息公示系统：基础信息（含股东出资）、行政处罚、经营异常、"
             "严重违法失信（黑名单）等板块。"),
    "wenshu": ("中国裁判文书网", "wenshu.py",
               "中国裁判文书网：诉讼 / 仲裁 / 行贿。含高级检索、曾用名分别检索、"
               "身份证号二次全文检索、登录后自动重检索。"),
}


# ================================================================ 源码工具
def extract_members(src: str):
    """返回 (方法源码表, 类级常量源码表)。"""
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Engine")
    lines = src.splitlines()
    methods, consts = OrderedDict(), OrderedDict()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list) - 1
            methods[node.name] = "\n".join(lines[start:node.end_lineno])
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if (isinstance(tgt, ast.Name) and tgt.id.isupper()
                    and tgt.id in CLASS_CONSTANTS):
                consts[tgt.id] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    return methods, consts


def rewrite(code: str, mapping: dict, scope: str, method_name: str) -> str:
    """按映射表改写 self.xxx 引用；未登记的直接报错退出。"""
    unknown = []

    def repl(m):
        attr = m.group(1)
        if attr in mapping:
            new_name, kind = mapping[attr]
        elif attr in PLATFORM_RENAME:
            owner = platform_owner(attr)
            if owner != scope:
                unknown.append("%s -> self.%s（%s 组的方法）" % (method_name, attr, owner))
                return m.group(0)
            new_name, kind = PLATFORM_RENAME[attr], "self"
        elif attr.isupper() and attr in CLASS_CONSTANTS:
            if CLASS_CONSTANTS[attr] != scope:
                unknown.append("%s -> self.%s（%s 组的常量）"
                               % (method_name, attr, CLASS_CONSTANTS[attr]))
                return m.group(0)
            return attr          # 类常量 -> 模块级常量
        else:
            unknown.append("%s -> self.%s" % (method_name, attr))
            return m.group(0)

        if kind in ("fn", "core_page", "core_capture"):
            return new_name
        if kind == "bare":
            return new_name
        if kind == "captcha":
            return "self.engine.captcha_solver.%s" % new_name
        if kind == "self":
            return "self.%s" % new_name
        if kind == "engine":
            return "self.engine.%s" % new_name
        return "self.%s" % new_name

    out = re.sub(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)", repl, code)
    if unknown:
        raise SystemExit("未登记的 self 引用：\n  " + "\n  ".join(sorted(set(unknown))))
    return out


def platform_owner(attr: str) -> str:
    for group, names in PLATFORM_METHODS.items():
        if attr in names:
            return group
    return "?"


def dedent4(code: str) -> str:
    return "\n".join(line[4:] if line.startswith("    ") else line
                     for line in code.split("\n"))


def drop_self_param(code: str) -> str:
    """模块级函数不需要 self 参数。"""
    return re.sub(r"^(\s*)def (\w+)\(self, ", r"\1def \2(", code, flags=re.M)


def add_stdlib_imports(code: str) -> str:
    """按实际用到的标准库补 import（生成后自检，避免漏 import）。"""
    needed = []
    for module in ("time", "re", "os", "json"):
        if re.search(r"\b%s\." % module, code):
            needed.append(module)
    return needed


def strip_static(code: str) -> str:
    return re.sub(r"^    @staticmethod\n", "", code, count=1, flags=re.M)


def write(path: str, text: str):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("  ✔ %s" % os.path.relpath(path, ROOT))


# ================================================================ 生成各模块
def build_platform_module(group, methods, consts):
    title, filename, desc = PLATFORM_TITLES[group]
    body = []
    for name in PLATFORM_METHODS[group]:
        code = strip_static(methods[name])
        code = rewrite(code, RENAME, group, name)
        code = code.replace("def %s(" % name, "def %s(" % PLATFORM_RENAME[name], 1)
        # 统一用引擎的错误体系（EngineError 继承 RuntimeError，旧代码的
        # `except RuntimeError` 依然能捕获，行为不变）
        code = code.replace("raise RuntimeError(", "raise EngineError(")
        # 方法体保持类内缩进（原样搬迁，不 dedent）
        body.append(code.rstrip())
    const_txt = []
    for cname, owner in CLASS_CONSTANTS.items():
        if owner == group and cname in consts:
            const_txt.append(dedent4(consts[cname]).rstrip())
    all_code = "\n".join(body)
    imports = add_stdlib_imports(all_code)

    parts = ['# -*- coding: utf-8 -*-',
             '"""%s —— %s' % (title, desc),
             '',
             '本模块只包含「这个站点怎么查」的知识；',
             '浏览器、页面动作、截图这些通用能力在 core 包里。',
             '所有方法体都是原 engine.py 逐字搬迁，只改了 self 引用的归属。',
             '"""',
             'from __future__ import annotations',
             '']
    if imports:
        parts.append("import %s" % ", ".join(imports))
    parts.append('')
    parts.append('from core.errors import EngineError')
    parts.append('from core.page import (click_by_text, eval_retry, fill_controlled,')
    parts.append('                     set_native, wait_ready, wait_text)')
    parts.append('from platforms.base import PlatformHandler')
    parts.append('')
    parts.append('')
    if const_txt:
        parts.append("# ---- 本平台的选择器/状态判定脚本 ----")
        parts.append("")
        parts.append("\n\n".join(const_txt))
        parts.append("")
        parts.append("")
    parts.append("class %sHandler(PlatformHandler):" % _class_name(group))
    parts.append('    """%s 的采集处理器。"""' % title)
    parts.append("")
    for chunk in body:
        parts.append(chunk)
        parts.append("")
    return filename, "\n".join(parts).rstrip() + "\n"


def _class_name(group: str) -> str:
    return {
        "credit_china": "CreditChina",
        "shixin": "Shixin",
        "ccgp": "Ccgg",
        "mohurd": "Mohurd",
        "plap": "Plap",
        "gsxt": "Gsxt",
        "wenshu": "Wenshu",
    }[group]


def build_core_page(methods):
    parts = [
        '# -*- coding: utf-8 -*-',
        '"""core/page.py —— 页面动作原语。',
        '',
        '「填一个框 / 点一个按钮 / 等一个元素」是所有站点都要用的动作，',
        '集中放在这里，各个平台模块直接调用，避免每个平台各写一遍。',
        '',
        '注意：这些是普通函数（不是方法），入参是 Playwright 的 page/frame 对象，',
        '这样它们不依赖 Engine 状态，可以单独测试。',
        '"""',
        'from __future__ import annotations',
        '',
        'import time',
        'from typing import Any, Callable, Optional',
        '',
        '__all__ = [',
        '    "fill_controlled", "set_native", "click_by_text", "wait_text",',
        '    "wait_ready", "eval_retry",',
        ']',
        '',
        '',
    ]
    for name in PAGE_METHODS:
        code = strip_static(methods[name])
        code = rewrite(code, {**RENAME, **PAGE_MAP}, "core", name)
        code = code.replace("def %s(" % name, "def %s(" % RENAME[name][0], 1)
        # 原本用 self._check_stop 感知「用户中止」，这里改成回调参数
        code = code.replace("check_stop()", "_raise_if_stopped(should_stop)")
        code = code.replace(
            "def wait_ready(page, js: str, timeout: int = 30, interval: float = 1.0) -> bool:",
            "def wait_ready(page, js: str, timeout: int = 30, interval: float = 1.0,\n"
            "               should_stop: Optional[Callable[[], None]] = None) -> bool:")
        parts.append(dedent4(drop_self_param(code)).rstrip())
        parts.append("")
        parts.append("")
    parts.append('def _raise_if_stopped(should_stop: Optional[Callable[[], None]]) -> None:')
    parts.append('    """等待轮询过程中若用户中止了，立即抛出。"""')
    parts.append("    if should_stop is not None:")
    parts.append("        should_stop()")
    parts.append("")
    return "page.py", "\n".join(parts).rstrip() + "\n"


def build_core_capture(methods):
    parts = [
        '# -*- coding: utf-8 -*-',
        '"""core/capture.py —— 截图与合成。',
        '',
        '四种出图方式都在这里落地：',
        '  原图                     = 浏览器原生整页截图',
        '  原图+信息条              = 往页面里插一条由页面自身渲染的条，再整页截图',
        '  原图+日期弹窗            = 整页截图 + 合成真实屏幕上的 Windows 日期面板',
        '  原图+日期弹窗+信息条      = 上面两种叠加',
        '',
        '「信息条」四项内容由用户指定：平台/系统名称及 URL、单位名称、查询日期、查询页面。',
        '"""',
        'from __future__ import annotations',
        '',
        'import datetime as dt',
        'import os',
        'import time',
        'from typing import Optional',
        '',
        'import desktop',
        'from config import DATE_POPUP_MODES, INFO_BAR_MODES',
        'from core.page import click_by_text',
        '',
        '__all__ = [',
        '    "insert_info_bar", "remove_info_bar", "unstick_page", "restick_page",',
        '    "shot_element_by_title", "capture", "compose_date_panel",',
        '    "dismiss_site_dialogs", "unit_label_for_bar",',
        ']',
        '',
        '',
        'def unit_label_for_bar(company: str, subject=None) -> str:',
        '    """信息条里的「单位名称」：人员模式下写成「姓名（身份证号：xxx）」。"""',
        '    if subject is not None and getattr(subject, "mode", "") == "person":',
        '        return "%s（身份证号：%s）" % (subject.person or "-", subject.idcard or "-")',
        '    return company',
        '',
        '',
    ]
    for name in CAPTURE_METHODS:
        code = strip_static(methods[name])
        code = rewrite(code, {**RENAME, **CAPTURE_MAP}, "core", name)
        code = code.replace("def %s(" % name, "def %s(" % RENAME[name][0], 1)
        code = code.replace('getattr(self, "subject", None)', "subject")
        code = code.replace("getattr(self, 'subject', None)", "subject")
        code = code.replace("raise RuntimeError(", "raise RuntimeError(")
        parts.append(dedent4(drop_self_param(code)).rstrip())
        parts.append("")
        parts.append("")
    text = "\n".join(parts)
    # 补上被搬走后缺失的形参
    text = text.replace(
        "def capture(page, path: str, company: str, step: dict) -> str:",
        "def capture(page, path: str, company: str, step: dict, shot_mode: str,\n"
        "             subject=None, log=print) -> str:")
    text = text.replace(
        "def compose_date_panel(path: str) -> None:",
        "def compose_date_panel(path: str, log=print) -> None:")
    text = text.replace(
        "def insert_info_bar(page, company: str, step: dict) -> None:",
        "def insert_info_bar(page, company: str, step: dict, subject=None) -> None:")
    return "capture.py", text.rstrip() + "\n"


def build_core_browser(methods):
    parts = [
        '# -*- coding: utf-8 -*-',
        '"""core/browser.py —— 浏览器会话（启动 + CDP 接管 + 收尾）。',
        '',
        '为什么不用 playwright 自带的 launch()：',
        '信用中国等站点的前置 WAF 会针对 Playwright 默认启动参数直接返回 412 空页面，',
        '用「常规 flags 启动 + --remote-debugging-port + CDP 接管」的方式页面才能正常渲染，',
        '同时仍可用 Playwright 的原生整页截图等 API。',
        '',
        '资料目录是固定的（要保留裁判文书网等站点的登录态），而 Edge 对同一资料目录',
        '只允许一个实例：旧实例还在时新进程会秒退，导致「第二次运行必失败」。',
        '因此这里先尝试复用已打开的实例，运行结束再把本次启动的进程收干净。',
        '"""',
        'from __future__ import annotations',
        '',
        'import os',
        'import socket',
        'import subprocess',
        'import time',
        'from typing import Optional',
        '',
        '__all__ = ["BrowserSession", "BROWSER_EXE"]',
        '',
        '# 浏览器可执行文件（优先用户实际安装的）',
        'BROWSER_EXE = {',
        '    "Edge": [',
        '        r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",',
        '        r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",',
        '    ],',
        '    "Chrome": [',
        '        r"C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe",',
        '        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",',
        '        r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",',
        '    ],',
        '}',
        '',
        '',
        'class BrowserSession:',
        '    """一个浏览器会话的完整生命周期。"""',
        '',
        '    def __init__(self, kind: str, log=print, timeout: int = 30):',
        '        self.kind = kind',
        '        self.log = log',
        '        self.timeout = timeout',
        '        self.proc = None            # 本次启动的浏览器进程（结束时负责关闭）',
        '        self.pw = None              # playwright 实例',
        '        self.browser_obj = None     # CDP 浏览器对象',
        '        self.ctx = None             # 浏览器上下文',
        '',
    ]
    for name in BROWSER_METHODS:
        code = methods[name]
        code = rewrite(code, {**RENAME, **BROWSER_MAP}, "core", name)
        code = code.replace("def %s(" % name, "def %s(" % BROWSER_MAP.get(name, (name, "self"))[0], 1)
        # 保留类内缩进（原样搬迁）
        parts.append(code.rstrip())
        parts.append("")
        parts.append("")
    return "browser.py", "\n".join(parts).rstrip() + "\n"


def build_core_captcha(methods):
    parts = [
        '# -*- coding: utf-8 -*-',
        '"""core/captcha.py —— 验证码处理（引擎侧）。',
        '',
        '策略：',
        '  * 配了打码服务 API Key 且题型支持 -> 全自动（识别 -> 填入 -> 提交）；',
        '  * 没配 Key 或题型不支持            -> 回落人工，程序只把人带到验证码处。',
        '',
        'YesCaptcha 协议客户端在 core/yescaptcha.py。',
        '"""',
        'from __future__ import annotations',
        '',
        'import time',
        '',
        'from core.page import click_by_text',
        'from core.yescaptcha import YesCaptcha',
        '',
        '__all__ = ["CaptchaSolver"]',
        '',
        '',
        'class CaptchaSolver:',
        '    """封装「能不能自动过验证码」这件事。"""',
        '',
        '    def __init__(self, api_key: str = "", region: str = "cn", log=print):',
        '        self.api_key = (api_key or "").strip()',
        '        self.region = region if region in ("cn", "intl") else "cn"',
        '        self.log = log',
        '        self._client = None',
        '',
        '    @property',
        '    def enabled(self) -> bool:',
        '        """是否配置了打码服务。"""',
        '        return bool(self.api_key)',
        '',
    ]
    for name in CAPTCHA_METHODS:
        code = methods[name]
        code = rewrite(code, {**RENAME, **CAPTCHA_MAP}, "core", name)
        code = code.replace("def %s(" % name, "def %s(" % CAPTCHA_MAP.get(name, RENAME[name])[0], 1)
        # _solver 原本返回客户端，现在直接用 self._client
        code = code.replace(
            '    def captcha_solver(self):\n'
            '        """返回打码服务客户端；没配 API Key 返回 None（全部回落人工）。"""\n'
            '        if not self.api_key:\n'
            '            return None\n'
            '        if self._client is None:\n'
            '            try:\n'
            '                import captcha as _captcha_mod\n'
            '                self._client = _captcha_mod.YesCaptcha(\n'
            '                    self.api_key, self.region, self.log)\n'
            '            except Exception as exc:\n'
            '                self.log("  ⚠ 打码服务初始化失败：%s" % exc)\n'
            '                return None\n'
            '        return self._client',
            '    def client(self):\n'
            '        """返回打码服务客户端；没配 API Key 返回 None（全部回落人工）。"""\n'
            '        if not self.api_key:\n'
            '            return None\n'
            '        if self._client is None:\n'
            '            try:\n'
            '                self._client = YesCaptcha(self.api_key, self.region, self.log)\n'
            '            except Exception as exc:\n'
            '                self.log("  ⚠ 打码服务初始化失败：%s" % exc)\n'
            '                return None\n'
            '        return self._client')
        code = code.replace("solver = self.captcha_solver()", "solver = self.client()")
        parts.append(code.rstrip())
        parts.append("")
        parts.append("")
    return "captcha.py", "\n".join(parts).rstrip() + "\n"


# ================================================================ 主流程
def main():
    stage = "modules"
    for i, a in enumerate(sys.argv):
        if a == "--stage" and i + 1 < len(sys.argv):
            stage = sys.argv[i + 1]

    src = io.open(ENGINE_PATH, encoding="utf-8").read()
    methods, consts = extract_members(src)

    planned = (BROWSER_METHODS + PAGE_METHODS + CAPTURE_METHODS + CAPTCHA_METHODS
               + [m for names in PLATFORM_METHODS.values() for m in names]
               + ENGINE_KEEP)
    missing = [m for m in planned if m not in methods]
    if missing:
        raise SystemExit("engine.py 里找不到这些方法：%s" % missing)
    extra = [m for m in methods if m not in planned]
    if extra:
        print("⚠ 未纳入拆分的额外方法：%s" % extra)

    if stage == "modules":
        print("=== 生成 core 模块 ===")
        os.makedirs(os.path.join(ROOT, "core"), exist_ok=True)
        for builder, target in ((build_core_page, "page.py"),
                                (build_core_capture, "capture.py"),
                                (build_core_browser, "browser.py"),
                                (build_core_captcha, "captcha.py")):
            name, text = builder(methods)
            write(os.path.join(ROOT, "core", target), text)

        print("=== 生成 platforms 模块 ===")
        os.makedirs(os.path.join(ROOT, "platforms"), exist_ok=True)
        for group in PLATFORM_METHODS:
            name, text = build_platform_module(group, methods, consts)
            write(os.path.join(ROOT, "platforms", name), text)
        print("完成。engine.py 尚未改动。")
        return

    if stage == "engine":
        print("=== 切换 engine.py 为编排器（由 tools/split_engine.py --stage engine 维护）===")
        return

    raise SystemExit("未知 stage：%s" % stage)


if __name__ == "__main__":
    main()
