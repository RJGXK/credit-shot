# -*- coding: utf-8 -*-
"""企业信用一键截图工具 —— 编排器（Engine）。

这一层只做四件事：

1. **组装**：创建浏览器会话、验证码服务、7 个平台处理器；
2. **编排**：按「查询主体 × 采集项」的顺序调度，带节流；
3. **交互**：处理【继续 / 跳过 / 中止】三个指令与人工挂起；
4. **汇总**：把每个采集项的结果收成 StepResult 列表。

站点知识全在 ``platforms/`` 包里，通用能力（浏览器、页面动作、截图、验证码）
全在 ``core/`` 包里，这一层不包含任何「某个站点怎么查」的内容。

对外接口保持不变::

    engine = Engine(output_dir=..., browser=..., shot_mode=..., ...)
    results = engine.run(companies, step_keys)   # -> List[StepResult]
    engine.self_check()
"""
from __future__ import annotations

import os
import time
from typing import Callable, List, Optional

import desktop
from config import (DEFAULTS, LABEL_OF_MODE, MODE_PERSON, all_steps,
                    step_supports)
from core.browser import BrowserSession
from core.captcha import CaptchaSolver
from core.control import Control
from core.errors import Aborted, EngineError, Skipped
from core.result import StepResult
from core.subject import (Subject, looks_like_idcard, parse_subject,
                          safe_name, split_company)
from platforms import build_handlers
from platforms.base import GROUP_BY_KEY, STEP_ENTRY_BY_KIND

__all__ = [
    "Engine", "StepResult", "Subject", "Control", "Aborted", "Skipped",
    "EngineError", "make_pdf", "parse_subject", "split_company",
    "looks_like_idcard", "safe_name",
]

#: 采集项类型（kind）-> 负责它的平台处理器
STEP_HANDLER_BY_KIND = {
    "creditchina": "credit_china",
    "creditchina_person": "credit_china",
    "zxgk": "shixin",
    "ccgp": "ccgp",
    "gsxt_basic": "gsxt",
    "gsxt_section": "gsxt",
    "gsxt_blacklist": "gsxt",
    "cnca": "cnca",
}

#: 共享会话分组（group）-> 负责它的平台处理器
GROUP_HANDLER_BY_KEY = {
    "mohurd": "mohurd",
    "plap": "plap",
    "gsxt_detail": "gsxt",
    "ws": "wenshu",
    "ws_xinghui": "wenshu",
    "cnca": "cnca",
}


class Engine:
    """执行截图任务。"""

    def __init__(
        self,
        output_dir: str,
        browser: str = DEFAULTS["browser"],
        shot_mode: str = DEFAULTS["shot_mode"],
        subject_mode: str = "company",
        pace_seconds: int = DEFAULTS["pace_seconds"],
        timeout: int = DEFAULTS["timeout"],
        make_pdf: bool = False,
        credentials: Optional[dict] = None,
        captcha_key: str = "",
        captcha_region: str = "cn",
        log: Callable[[str], None] = print,
        control: Optional[Control] = None,
        manual_timeout: int = 900,
    ):
        self.output_dir = os.path.abspath(output_dir)
        self.browser = browser
        self.shot_mode = shot_mode
        self.subject_mode = subject_mode
        self.pace_seconds = max(0, int(pace_seconds))
        self.timeout = int(timeout)
        self.make_pdf = make_pdf
        # 账号凭据：{platform_key: {"username":…, "password":…}}
        # 只在内存里，日志一律脱敏输出，绝不打印密码。
        self.credentials = dict(credentials or {})
        self.log = log
        self.control = control or Control()
        # 挂起等人工处理的时限（秒）。无人值守/自动化跑批时可调小。
        self.manual_timeout = max(30, int(manual_timeout))

        # ---- 组装各部件 ----
        self.browser_session = BrowserSession(self.browser, self.log, self.timeout)
        self.captcha_solver = CaptchaSolver(captcha_key, captcha_region, self.log,
                                            should_stop=self.check_stop)
        self.handlers = build_handlers(self)
        # 导航层的等待也走可中断等待，进入站点时同样能响应跳过/中止
        try:
            from core import nav as _nav
            _nav.set_nap(self.control.wait)
        except Exception:
            pass

        # ---- 跨步骤共享的运行状态 ----
        self.current_subject: Optional[Subject] = None   # 当前查询主体
        self.vcode_ok = False    # 信用中国 5 分钟内免验证码标记

    # ------------------------------------------------------------------ 节流
    def pace(self, why: str = "") -> None:
        """按配置节流，模拟正常使用频率，避免触发站点风控。

        ��流期间的处理原则：
        * 【中止】-> 立刻抛 Aborted，整轮收尾；
        * 【跳过此步】-> **不在这里消费**（消费了就没人跳了），
          只提前结束节流，把信号留给下一个步骤边界去跳过那一步。
        """
        total = self.pace_seconds
        if total <= 0:
            return
        self.log("节流等待 %d 秒%s（模拟正常使用频率，避免风控）…" % (total, why))
        deadline = time.time() + total
        while True:
            if self.control.stop.is_set():
                raise Aborted()
            if self.control.skip.is_set():
                self.log("  → 收到【跳过此步】，提前结束节流（下一步将跳过）。")
                return
            left = int(deadline - time.time())
            if left <= 0:
                break
            if left <= 3 or left % 10 == 0:
                self.log("  …还剩 %d 秒" % left)
            time.sleep(min(1.0, max(0.05, deadline - time.time())))

    def sleep(self, seconds: float) -> None:
        """可被【中止】/【跳过此步】打断的等待。

        平台层所有固定时长的等待都必须走这里 —— 用 ``time.sleep`` 的话，
        用户点了【跳过此步】引擎要等整段睡完才有反应，表现为「跳过失效」。
        """
        self.control.wait(seconds)

    def check_stop(self) -> None:
        """用户中止或跳过当前步骤。

        中止 -> 抛 Aborted 结束全局
        跳过 -> 抛 Skipped 结束当前步骤并流转到下一步
        """
        if self.control.stop.is_set():
            raise Aborted()
        if self.control.skip.is_set():
            self.control.skip.clear()
            raise Skipped()

    def wait_manual(self, prompt: str, timeout: int = 0) -> str:
        """挂起等待人工处理。

        收到【我已处理，继续截图】返回 'resume'；收到【跳过此步】抛 Skipped。
        timeout 传 0 表示用引擎默认的 ``manual_timeout``（默认 900 秒）。
        """
        self.check_stop()
        timeout = int(timeout) or self.manual_timeout
        # 用户可能在到达等待点之前就点了按钮，这里直接沿用该指令，别让用户白等
        if self.control.resume.is_set():
            self.control.clear()
            self.log("  → 收到此前已发出的【继续】指令，直接继续。")
            return "resume"
        if self.control.skip.is_set():
            self.control.clear()
            self.log("  → 收到此前已发出的【跳过】指令，跳过本步。")
            raise Skipped()
        self.control.clear()
        self.log("⏸ " + prompt)
        self.log("  → 处理完成后点【我已处理，继续截图】；无法处理则点【跳过此步】。")
        self.control.waiting.set()
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.control.stop.is_set():
                    raise Aborted()
                if self.control.skip.is_set():
                    self.control.clear()
                    self.log("  → 已跳过本步。")
                    raise Skipped()
                if self.control.resume.is_set():
                    self.control.clear()
                    self.log("  → 收到继续指令。")
                    return "resume"
                time.sleep(0.25)
            self.log("  → 等待超时，按继续处理。")
            return "resume"
        finally:
            self.control.waiting.clear()

    # ------------------------------------------------------------ 浏览器接管
    def open_browser(self):
        """启动浏览器并接管，返回 (playwright, browser, context, page)。"""
        return self.browser_session.open()

    def close_browser(self) -> None:
        """收干净浏览器（断开 CDP + 结束本次启动的进程树）。"""
        self.browser_session.close()

    @property
    def ctx(self):
        """浏览器上下文（CDP 接管之后才有值）。

        平台处理器要用它找「站点自己开的新标签页」（住建部企业详情页就是新标签）。
        之前这里没有这个属性，mohurd 里写 self.engine.ctx 会直接抛
        ``'Engine' object has no attribute 'ctx'`` —— 整条住建部流程中断。
        """
        return getattr(self.browser_session, "ctx", None)

    def browser_pages(self):
        """当前浏览器里的全部标签页（拿不到就返回空列表）。"""
        ctx = self.ctx
        if ctx is None:
            return []
        try:
            return list(ctx.pages)
        except Exception:
            return []

    # 兼容旧调用名
    _open_browser = open_browser
    _close_browser = close_browser

    # ------------------------------------------------------------------ 登录
    def auto_login(self, page, platform_key: str, platform_name: str) -> bool:
        """用配置好的账号密码自动登录；成功返回 True。

        遇到验证码会把控制权交回界面（挂起等人工），
        人工补完验证码后程序继续提交并判定结果。
        """
        from auth.autologin import try_login
        from auth.credentials import mask_username

        cred = self.credentials.get(platform_key) or {}
        username = (cred.get("username") or "").strip()
        password = cred.get("password") or ""
        if not username or not password:
            # 静默跳过是最难受的：日志里什么都没有，用户完全不知道
            # 自动登录为什么没跑、该去哪里补配置。
            missing = []
            if not username:
                missing.append("账号")
            if not password:
                missing.append("密码")
            self.log("  ⚠ %s 未自动登录：%s未配置"
                     % (platform_name, "、".join(missing) if missing else "账号密码"))
            self.log("    → 打开「账号密码」填写后点「保存到本地」（密码留空表示不修改）")
            return False

        self.log("  使用已配置的账号自动登录：%s（账号 %s）"
                 % (platform_name, mask_username(username)))

        def wait_captcha(prompt: str) -> None:
            # 引擎侧挂起：界面会提示「等待人工处理」，用户补完验证码点继续
            self.wait_manual(prompt)

        def solve_captcha(frame) -> bool:
            # 打码服务自动过图形验证码；没配 API Key 直接返回 False 走人工
            return self.captcha_solver.solve_frame_captcha(frame)

        try:
            res = try_login(page, platform_key, username, password,
                            self.log, wait_captcha, solve_captcha)
        except Exception as exc:
            self.log("  ⚠ 自动登录异常：%s" % exc)
            return False

        if res.ok:
            self.log("  ✔ %s 自动登录成功" % platform_name)
            return True
        if res.bad_credentials:
            self.log("  ✘ %s 自动登录失败：账号或密码不正确（请检查「账号密码」里的配置）"
                     % platform_name)
            return False
        if res.needs_captcha:
            self.log("  ⚠ %s 自动登录未完成：验证码未通过，已挂起等人工处理" % platform_name)
            return False
        self.log("  ⚠ %s 自动登录未完成：%s" % (platform_name, res.reason))
        return False

    # ------------------------------------------------------------------ 截图
    def shot_step(self, page, company: str, step: dict) -> str:
        """截图并落盘，返回文件路径。"""
        from core.capture import capture

        subj = self.current_subject
        tag = subj.label() if subj else company
        fname = "%s_%s_%s.png" % (step["no"], step["short"], safe_name(tag))
        path = os.path.join(self.output_dir, fname)
        capture(page, path, company, step, self.shot_mode,
                subject=subj, log=self.log)
        self.log("  ✔ 已保存：%s" % path)
        return path

    # ------------------------------------------------------------------ 调度
    def run_single_step(self, page, company: str, code: str, step: dict) -> None:
        """把一个采集项分派给对应的平台处理器。"""
        kind = step.get("kind", "")
        entry = STEP_ENTRY_BY_KIND.get(kind)
        handler_key = STEP_HANDLER_BY_KIND.get(kind)
        if entry is None or handler_key is None:
            raise EngineError("未实现的采集类型：%s" % kind)
        handler = self.handlers.get(handler_key)
        if handler is None:
            raise EngineError("没有对应的平台处理器：%s" % handler_key)
        getattr(handler, entry)(page, company, code, step)

    def run_group(self, page, company: str, gkey: str, gsteps: list,
                  results: List[StepResult], shots: List[str]) -> None:
        """按分组执行采集项：同组的项共用一次「进入站点」。"""
        if gkey in GROUP_BY_KEY:
            handler_key = GROUP_HANDLER_BY_KEY.get(gkey)
            handler = self.handlers.get(handler_key or "")
            if handler is not None:
                # 分组处理器内部逐项执行，某一项抛 Skipped 不应该终止整组，
                # 由处理器自己 catch；这里只兜底「整组都没开始就跳过」的情况。
                try:
                    handler.collect_group(page, company, gsteps, results, shots)
                except Skipped:
                    self.log("  ⤼ 本组已跳过")
                    for step in gsteps:
                        results.append(StepResult(step["no"], step["key"],
                                                  step["title"], company,
                                                  False, message="已跳过"))
                return
        for si, step in enumerate(gsteps):
            if si > 0:
                self.pace("（下一采集项前）")
            self.run_one(page, company, step, results, shots)

    def run_one(self, page, company: str, step: dict,
                results: List[StepResult], shots: List[str]) -> None:
        """执行单个采集项并截图（含异常/跳过处理）。"""
        self.check_stop()
        t0 = time.time()
        self.log("[%s] %s" % (step["no"], step["title"]))
        subj = self.current_subject
        tag = subj.label() if subj else company
        code = subj.code if subj else ""
        try:
            self.run_single_step(page, company, code, step)
            path = self.shot_step(page, company, step)
            shots.append(path)
            results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                      True, path=path, elapsed=time.time() - t0))
        except Skipped:
            self.log("  ⤼ 本步已跳过")
            results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                      False, message="已跳过"))
        except Aborted:
            raise
        except Exception as exc:
            self.log("  ✘ 失败：%s" % str(exc).splitlines()[0])
            results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                      False, message=str(exc), elapsed=time.time() - t0))

    # ------------------------------------------------------------------ 主流程
    def run(self, companies: List[str], step_keys: List[str]) -> List[StepResult]:
        """companies 每行一个查询主体，格式见 Subject（按 subject_mode 解析）。"""
        os.makedirs(self.output_dir, exist_ok=True)
        results: List[StepResult] = []
        mode_label = LABEL_OF_MODE.get(self.subject_mode, "单位")

        selected = [s for s in all_steps() if s["key"] in step_keys]
        if not selected:
            return results

        # 按查询模式过滤：只收录单位的名单在人员模式下不跑，反之亦然
        usable, dropped = [], []
        for s in selected:
            (usable if step_supports(s, self.subject_mode) else dropped).append(s)
        if dropped:
            self.log("查询模式＝%s，以下 %d 个采集项不适用本次查询，已跳过：%s"
                     % (mode_label, len(dropped),
                        "、".join("%s %s" % (s["no"], s["short"]) for s in dropped)))
        if not usable:
            self.log("没有适用于「%s」模式的采集项，已结束。" % mode_label)
            return results
        selected = usable

        # 共享会话分组：同一 group 的采集项只做一次「进入站点」的动作
        # （同组项在目录上可以不连续：gsxt 的 21/23/24/25 都进同一个企业详情页）
        group_map: dict = {}
        group_order: List[str] = []
        for s in selected:
            g = s.get("group", s["kind"])
            if g not in group_map:
                group_map[g] = []
                group_order.append(g)
            group_map[g].append(s)
        groups = [(g, group_map[g]) for g in group_order]

        try:
            pw, browser, ctx, page = self.open_browser()
            self.log("浏览器已就绪：%s" % self.browser)
            self.log("本次采集项（%s模式）：%s"
                     % (mode_label, "、".join("%s %s" % (s["no"], s["short"]) for s in selected)))

            for ci, raw_line in enumerate(companies):
                subj = parse_subject(raw_line, self.subject_mode)
                company, code = subj.company, subj.code
                # 供各站点流程读取人员姓名/身份证号
                self.current_subject = subj
                # 换主体后要重置各平台的会话状态（如是否已在企业详情页）
                for handler in self.handlers.values():
                    handler.reset_subject_state()
                if ci > 0:
                    self.pace("（换下一个主体前）")
                self.log("=" * 62)
                self.log("主体 %d/%d：%s" % (ci + 1, len(companies), subj.describe()))
                if self.subject_mode == MODE_PERSON:
                    if not subj.person.strip():
                        self.log("  ⚠ 本行没有人员姓名，将无法查询")
                    if subj.idcard.strip() and not looks_like_idcard(subj.idcard):
                        self.log("  ⚠ 第 2 段「%s」不像身份证号（应为 15/18 位），已按原值填入"
                                 % subj.idcard.strip())
                shots: List[str] = []

                for gi, (gkey, gsteps) in enumerate(groups):
                    if gi > 0:
                        self.pace("（下一采集站点前）")
                    self.log("-" * 62)
                    self.log("▌分组 %s：%s" % (gkey, "、".join(s["short"] for s in gsteps)))
                    self.run_group(page, company, gkey, gsteps, results, shots)

                if self.make_pdf and shots:
                    pdf = os.path.join(self.output_dir, "%s_汇总.pdf" % safe_name(subj.label()))
                    try:
                        make_pdf(shots, pdf)
                        self.log("  ✔ PDF 汇总：%s（%d 页）" % (pdf, len(shots)))
                    except Exception as exc:
                        self.log("  ✘ PDF 生成失败：%s" % exc)
        except Aborted:
            self.log("已中止。")
        except Skipped:
            # Skipped 继承 BaseException，不会被下面的 except Exception 捕获，
            # 必须显式处理，否则会变成未捕获异常直接把线程打死。
            self.log("已跳过剩余步骤。")
        except Exception as exc:
            self.log("致命错误：%s" % exc)
        finally:
            try:
                self.close_browser()
            except Exception:
                pass
        return results

    # ------------------------------------------------------------------ 自检
    def self_check(self) -> bool:
        """功能自检：不联外网，验证浏览器驱动 + 原生整页截图 + 时间框渲染。"""
        from core.capture import insert_info_bar, remove_info_bar

        self.log("=" * 62)
        self.log("功能自检开始（不访问外网）")
        ok_all = True
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self.log("  ✘ Playwright 未安装：%s" % exc)
            return False
        self.log("  ✔ 浏览器驱动（playwright）可用")

        html = """<!doctype html><html><head><meta charset="utf-8">
        <style>body{font:16px/1.8 "Microsoft YaHei",sans-serif;margin:0;padding:24px;background:#fafafa}
        .box{border:1px solid #bbb;padding:18px;margin:14px 0;background:#fff}
        h1{color:#0b57d0}</style></head><body>
        <h1>功能自检页面</h1>
        <div class="box">用途：验证「原生整页截图」与「时间框渲染」是否正常。</div>
        <div class="box" id="t">时间框：<span id="ts"></span></div>
        <div class="box">下方留白用于验证整页截图高度是否超过一屏。</div>
        <div style="height:1400px"></div>
        <script>document.getElementById('ts').textContent=new Date().toLocaleString('zh-CN');</script>
        </body></html>"""
        tmp_html = os.path.join(self.output_dir, "_selfcheck.html")
        os.makedirs(self.output_dir, exist_ok=True)
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html)

        pw = browser = None
        try:
            pw, browser, ctx, page = self.open_browser()
            self.log("  ✔ 浏览器启动正常并已接管：%s" % self.browser)
            page.goto("file:///" + tmp_html.replace("\\", "/"), wait_until="load")
            page.wait_for_timeout(600)
            ts = page.inner_text("#ts")
            self.log("  ✔ 页面时间框渲染正常：%s" % ts)

            out = os.path.join(self.output_dir, "_selfcheck_fullpage.png")
            page.screenshot(path=out, full_page=True)
            size = os.path.getsize(out)
            self.log("  ✔ 原生整页截图成功：%s（%d KB）" % (out, size // 1024))

            step = {"no": "00", "short": "自检", "title": "功能自检",
                    "platform": "功能自检", "platform_url": "https://www.example.com/"}
            insert_info_bar(page, "自检企业", step, subject=None)
            out2 = os.path.join(self.output_dir, "_selfcheck_infobar.png")
            page.screenshot(path=out2, full_page=True)
            remove_info_bar(page)
            self.log("  ✔ 信息条模式截图成功：%s" % out2)

            # 日期弹窗：抓面板本身，并与页面原图合成
            pts = desktop.find_clock_points()
            if pts:
                self.log("  ✔ 已定位任务栏时钟：%s" % pts[:2])
            else:
                self.log("  ⚠ 未定位到任务栏时钟（日期面板可能点不开）")
            try:
                page.bring_to_front()
            except Exception:
                pass
            time.sleep(0.5)
            hwnd = desktop.find_browser_window(self.browser, page.title() or "")
            if hwnd:
                desktop.activate_window(hwnd, maximize=True)
                time.sleep(0.6)
            out3 = os.path.join(self.output_dir, "_selfcheck_datepanel.png")
            got = desktop.grab_date_panel(out3, self.log)
            if got:
                self.log("  ✔ 日期/时间面板抓取成功：%s" % out3)
                base = os.path.join(self.output_dir, "_selfcheck_compose.png")
                try:
                    from PIL import Image
                    im = Image.open(out)
                    pan = Image.open(out3).convert("RGBA")
                    x = max(0, im.width - pan.width - 20)
                    y = max(0, im.height - pan.height - 20)
                    im = im.convert("RGBA")
                    im.alpha_composite(pan, (x, y))
                    im.convert("RGB").save(base)
                    self.log("  ✔ 原图+日期弹窗合成成功：%s" % base)
                except Exception as exc:
                    self.log("  ⚠ 合成自检失败：%s" % exc)
            else:
                ok_all = False
                self.log("  ✘ 日期/时间面板未能展开")

            n = len(all_steps())
            self.log("  ✔ 采集项目录加载正常：%d 项（7 个站点）" % n)
        except Exception as exc:
            ok_all = False
            self.log("  ✘ 自检失败：%s" % exc)
        finally:
            try:
                self.close_browser()
            except Exception:
                pass
        self.log("自检结果：%s" % ("全部通过" if ok_all else "存在失败项"))
        return ok_all


def make_pdf(images: List[str], out_pdf: str) -> str:
    """把多张图片按给定顺序合并成一个 PDF（图片本身不缩放、不合成）。"""
    from PIL import Image

    pages = []
    for p in images:
        if not os.path.exists(p):
            continue
        pages.append(Image.open(p).convert("RGB"))
    if not pages:
        raise RuntimeError("没有可合并的图片")
    pages[0].save(out_pdf, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return out_pdf
