# -*- coding: utf-8 -*-
"""登录 / 打码 / 凭据 三条链路的自检脚本。

不需要真浏览器、不需要真 API Key，全部用假对象跑通逻辑：
    python selftest.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import autologin
from auth import credentials as cred_mod
from core import yescaptcha as captcha_mod


# ==================================================================== 凭据
class TestCredentials(unittest.TestCase):
    def test_roundtrip_and_masking(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "凭据.ini")
            creds = [
                cred_mod.Credential("wenshu", "13800138000", "Pa$$w0rd%1#x", True),
                cred_mod.Credential("gsxt", "testuser", "pwd", False),
                cred_mod.Credential("creditchina", "", "", True),   # 空的不落盘
            ]
            self.assertTrue(cred_mod.save_credentials(creds, path))
            self.assertTrue(os.path.exists(path))

            loaded = cred_mod.load_credentials(path)
            by_key = {c.platform: c for c in loaded}
            self.assertIn("wenshu", by_key)
            self.assertNotIn("creditchina", by_key, "空凭据不应落盘")
            # 密码里的 % 和 # 必须原样读回（RawConfigParser，不做插值）
            self.assertEqual(by_key["wenshu"].password, "Pa$$w0rd%1#x")
            self.assertEqual(by_key["wenshu"].username, "13800138000")
            self.assertTrue(by_key["wenshu"].enabled)
            self.assertFalse(by_key["gsxt"].enabled)

    def test_credentials_to_map_only_usable(self):
        creds = [
            cred_mod.Credential("wenshu", "13800138000", "pw", True),
            cred_mod.Credential("gsxt", "u", "p", False),       # 未启用
            cred_mod.Credential("creditchina", "u", "", True),  # 密码空
        ]
        m = cred_mod.credentials_to_map(creds)
        self.assertEqual(list(m.keys()), ["wenshu"])
        self.assertEqual(m["wenshu"]["username"], "13800138000")

    def test_mask_username(self):
        self.assertEqual(cred_mod.mask_username("13800138000"), "138****8000")
        self.assertEqual(cred_mod.mask_username("abc"), "a**")
        self.assertEqual(cred_mod.mask_username(""), "")
        # 脱敏结果不能等于原文
        for u in ("13800138000", "zhangsan", "ab"):
            self.assertNotEqual(cred_mod.mask_username(u), u)

    def test_captcha_key_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "凭据.ini")
            cred_mod.save_credentials([cred_mod.Credential("wenshu", "a", "b", True)], path)
            cred_mod.save_captcha_key("KEY-123", path)
            self.assertEqual(cred_mod.load_captcha_key(path), "KEY-123")
            # 打码 Key 段不能被当成平台凭据读出来
            loaded = cred_mod.load_credentials(path)
            self.assertEqual([c.platform for c in loaded], ["wenshu"])

    def test_platform_by_host(self):
        p = cred_mod.platform_by_host("account.court.gov.cn")
        self.assertIsNotNone(p)
        self.assertEqual(p["key"], "wenshu")
        self.assertIsNone(cred_mod.platform_by_host("example.com"))


# ==================================================================== 打码
class _FakeResp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCaptcha(unittest.TestCase):
    def test_sync_task_payload_and_solution(self):
        sent = {}

        def fake_urlopen(req, timeout=None):
            sent["url"] = req.full_url
            sent["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResp({"errorId": 0, "solution": {"text": "8k3d"}})

        c = captcha_mod.YesCaptcha("KEY", "cn")
        with mock.patch.object(captcha_mod.urllib.request, "urlopen", fake_urlopen):
            out = c.solve_image_to_text(b"fake-png-bytes")
        self.assertEqual(out, "8k3d")
        self.assertIn("/createTask", sent["url"])
        self.assertEqual(sent["body"]["clientKey"], "KEY")
        # 2026-10 起 solve_image_to_text 优先用**异步题型 ImageToTextTask**
        # （官方标注识别率更高；实测信用中国描边验证码，同步题型会把
        #   描边阴影读成多余字符，异步题型读得更准），失败才回落 OcrBase。
        self.assertEqual(sent["body"]["task"]["type"], "ImageToTextTask")
        self.assertIn("body", sent["body"]["task"])

    def test_async_task_polls(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            path = req.full_url
            if path.endswith("/createTask"):
                return _FakeResp({"errorId": 0, "taskId": "T-1"})
            return _FakeResp({"errorId": 0, "status": "ready",
                               "solution": {"text": "ab12"}})

        c = captcha_mod.YesCaptcha("KEY", "cn", poll_interval=0)
        with mock.patch.object(captcha_mod.urllib.request, "urlopen", fake_urlopen):
            out = c.solve_image_to_text_async(b"png", numeric=4)
        self.assertEqual(out, "ab12")
        self.assertGreaterEqual(calls["n"], 2, "应先 createTask 再查结果")

    def test_error_code_translated(self):
        def fake_urlopen(req, timeout=None):
            return _FakeResp({"errorId": 1, "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
                               "errorDescription": "no key"})

        c = captcha_mod.YesCaptcha("BAD", "cn")
        with mock.patch.object(captcha_mod.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(captcha_mod.CaptchaError) as cm:
                c.get_balance()
        self.assertIn("API Key 不存在", str(cm.exception))

    def test_node_failover(self):
        """国内节点连不通时自动切国际节点。"""
        tried = []

        def fake_urlopen(req, timeout=None):
            tried.append(req.full_url)
            if "cn.yescaptcha.com" in req.full_url:
                raise OSError("连接超时")
            return _FakeResp({"errorId": 0, "balance": 12.5})

        c = captcha_mod.YesCaptcha("KEY", "cn")
        with mock.patch.object(captcha_mod.urllib.request, "urlopen", fake_urlopen):
            bal = c.get_balance()
        self.assertEqual(bal, 12.5)
        self.assertEqual(len(tried), 2, "应先试国内再试国际")
        self.assertIn("api.yescaptcha.com", tried[1])

    def test_empty_key_never_requests(self):
        c = captcha_mod.YesCaptcha("", "cn")
        def boom(*a, **k):
            raise AssertionError("没有 API Key 时不应该发请求")
        with mock.patch.object(captcha_mod.urllib.request, "urlopen", boom):
            with self.assertRaises(captcha_mod.CaptchaError):
                c.get_balance()


# ==================================================================== 登录
class _FakeFrame:
    """模拟统一身份认证 iframe。"""

    def __init__(self):
        self.url = "https://account.court.gov.cn/oauth/authorize?client_id=x"
        self.text = ""
        self.filled = []

    def wait_for_load_state(self, *a, **k):
        return None

    def evaluate(self, js, arg=None):
        if "document.body" in js:
            return self.text
        # gsxt 填值脚本一次填两个框（UserName / gsxtp），返回 "OK/OK"
        # —— 必须排在 Object.getOwnPropertyDescriptor 之前，
        #    因为 gsxt 的脚本里也用了原生 setter
        if "set('UserName'" in js:
            self.filled.append(arg)
            return "OK/OK"
        # 新版 _fill 一次 evaluate 完成「找 + 赋值 + 派发事件」
        if "Object.getOwnPropertyDescriptor" in js:
            self.filled.append(arg)
            return True
        if "querySelectorAll('input,textarea')" in js:
            kind = (arg or ["", "text"])[1] if isinstance(arg, (list, tuple)) else "text"
            return "pwdInput" if kind == "password" else "userInput"
        return True      # 点击类 JS


class _FakePage:
    def __init__(self, frame):
        self.frames = [frame]
        self.text = ""
        # gsxt 登录判定会用 page.url 判断「是否已跳回首页」；
        # 默认给登录子站 URL，让替身行为贴近真实站点
        self.url = "https://shiming.gsxt.gov.cn/socialuser-use-rllogin.html"

    def evaluate(self, js, arg=None):
        if "document.body" in js:
            return self.text
        # gsxt 填值脚本（一次填 UserName + gsxtp）
        if "set('UserName'" in js:
            frame = self.frames[0]
            frame.filled.append(arg)
            return "OK/OK"
        # gsxt 打开登录脚本：替身模拟「已在登录页」
        if "ALREADY" in js:
            return "ALREADY"
        return True

    def wait_for_function(self, js, arg=None, timeout=None):
        # 与 evaluate 同义（js_action 先试这个）；替身直接落 evaluate
        return self.evaluate(js, arg)


class _Clock:
    """虚拟时钟：sleep 立刻推进时间，避免测试空等真实时间。"""

    def __init__(self):
        self.t = 1_700_000_000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


class TestAutoLogin(unittest.TestCase):
    def setUp(self):
        self._clock = _Clock()
        self._patch = mock.patch.object(autologin, "time", self._clock)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_login_success_without_captcha(self):
        frame = _FakeFrame()
        page = _FakePage(frame)
        frame.text = "登录成功"

        res = autologin.try_login(page, "wenshu", "13800138000", "pw", print)
        self.assertTrue(res.ok, res.reason)
        self.assertTrue(res.filled)
        # 账号密码都被填了
        self.assertEqual(len(frame.filled), 2)

    def test_captcha_solved_by_service(self):
        """验证码 → 先走打码服务 → 成功，全程不挂起等人工。"""
        frame = _FakeFrame()
        page = _FakePage(frame)
        frame.text = "请输入验证码"

        calls = {"manual": 0, "auto": 0}

        def solve(frame_arg):
            calls["auto"] += 1
            frame.text = "登录成功"       # 模拟打码后校验通过
            return True

        def manual(prompt):
            calls["manual"] += 1

        res = autologin.try_login(page, "wenshu", "13800138000", "pw", print,
                                  manual, solve)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(calls["auto"], 1, "应先尝试打码服务")
        self.assertEqual(calls["manual"], 0, "打码成功就不该挂起人工")

    def test_captcha_falls_back_to_manual(self):
        """打码服务失败 → 挂起人工，人工处理后继续判成功。"""
        frame = _FakeFrame()
        page = _FakePage(frame)
        frame.text = "请输入验证码"

        def solve(frame_arg):
            return False                # 打码没通过

        def manual(prompt):
            frame.text = "登录成功"       # 人工补完验证码并登录

        res = autologin.try_login(page, "wenshu", "13800138000", "pw", print,
                                  manual, solve)
        self.assertTrue(res.ok, res.reason)

    def test_bad_credentials_detected(self):
        frame = _FakeFrame()
        page = _FakePage(frame)
        frame.text = "密码错误"

        res = autologin.try_login(page, "wenshu", "13800138000", "pw", print)
        self.assertFalse(res.ok)
        self.assertTrue(res.bad_credentials)
        self.assertIn("不正确", res.summary)

    def test_missing_credentials(self):
        res = autologin.try_login(_FakePage(_FakeFrame()), "wenshu", "", "", print)
        self.assertFalse(res.ok)
        self.assertIn("未配置", res.reason)

    def test_unsupported_platform(self):
        # 用一个**确实没有实现**的平台（ccgp 公开查询免登录，不需要自动登录）
        res = autologin.try_login(_FakePage(_FakeFrame()), "ccgp", "u", "p", print)
        self.assertFalse(res.ok)
        self.assertIn("暂不支持", res.reason)

    def test_gsxt_login_flow_registered(self):
        """gsxt 已实现自动登录流程，且账号密码填入成功。"""
        class _GsxtFrame(_FakeFrame):
            def __init__(self):
                super().__init__()
                self.url = "https://www.gsxt.gov.cn/index.html"
                self.text = ""

        frame = _GsxtFrame()
        page = _FakePage(frame)
        page.text = "退出登录"

        res = autologin.try_login(page, "gsxt", "13800138000", "pw", print)
        self.assertTrue(res.ok, res.reason)
        self.assertTrue(res.filled)
        # gsxt 一次 evaluate 同时填账号 + 密码
        self.assertEqual(len(frame.filled), 1)
        self.assertEqual(frame.filled[0]["u"], "13800138000")
        self.assertEqual(frame.filled[0]["p"], "pw")

    def test_no_password_in_log(self):
        """日志里绝不能出现密码原文。"""
        import io as _io
        buf = _io.StringIO()
        frame = _FakeFrame()
        page = _FakePage(frame)
        frame.text = "登录成功"
        autologin.try_login(page, "wenshu", "13800138000", "SUPERSECRET", buf.write)
        self.assertNotIn("SUPERSECRET", buf.getvalue())


class TestCaptchaRefresh(unittest.TestCase):
    """验证码「刷新重试」机制（用户反馈：第一次不显示，刷新几次才显示）。"""

    def _blank_png(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (120, 40), (250, 250, 250)).save(buf, format="PNG")
        return buf.getvalue()

    def _content_png(self):
        import io
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (120, 40), (255, 255, 255))
        d = ImageDraw.Draw(img)
        for i in range(4):
            x = 10 + i * 28
            d.rectangle([x, 10, x + 18, 30], fill=(20, 20, 20))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_blank_detection(self):
        from core.captcha import image_looks_blank
        self.assertTrue(image_looks_blank(self._blank_png()))
        self.assertFalse(image_looks_blank(self._content_png()))

    def test_refresh_retry_until_content(self):
        """前两次是白板 -> 程序自动刷新 -> 第 3 次识别成功。"""
        from core.captcha import CaptchaSolver

        state = {"shots": 0}

        class _Img:
            def screenshot(self, timeout=None):
                state["shots"] += 1
                return (self_holder.blank if state["shots"] < 3
                        else self_holder.content)

        class _Target:
            def __init__(self):
                self.blank = TestCaptchaRefresh()._blank_png()
                self.content = TestCaptchaRefresh()._content_png()

            def query_selector(self, sel):
                return _Img() if sel in ("img", "#vcodeimg") else None

            def evaluate(self, js, arg=None):
                if "hit.click()" in js or "arg.texts" in js:
                    return "CLICK:验证"
                if "cands" in js or "CLICK" in js:
                    return "CLICK:refresh"
                if "arg.text" in js:
                    return "OK"
                return True

            def query_selector_all(self, sel):
                return []

        self_holder = _Target()

        class _Solver:
            def solve_captcha_image_element(self, element, timeout=20):
                return "8K3P" if state["shots"] >= 3 else ""

        logs = []
        solver = CaptchaSolver.__new__(CaptchaSolver)
        solver.api_key = "x"
        solver.region = "cn"
        solver.log = logs.append
        solver._client = _Solver()

        ok = solver.solve_image_captcha(self_holder, img_selector="#vcodeimg",
                                        scope_selector=".vcodepop")
        self.assertTrue(ok, "刷新重试后应该识别成功")
        self.assertGreaterEqual(state["shots"], 3)
        self.assertTrue(any("刷新" in m for m in logs))


# ================================================================ 打码（手机号）
class TestWenshuPhoneMask(unittest.TestCase):
    """裁判文书网截图打码：只打手机号，不许伤到身份证号。"""

    _SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "platforms", "wenshu.py")

    def test_mask_regex_has_digit_guards(self):
        r"""打码正则必须带 (?<!\d)…(?!\d) 断言。

        没有断言时，18 位身份证号里「1+3~9」开头的 11 位子串
        （如 …19920313861…）会被当成手机号误改——v2.1.3 踩过。
        """
        with open(self._SRC, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("(?<!\\\\d)1[3-9]\\\\d{9}(?!\\\\d)", src,
                      "wenshu._mask_phones 的正则丢了非数字边界断言")

    def test_regex_semantics(self):
        """同语义在 Python 侧验证：身份证号不命中，手机号命中并被打码。"""
        import re
        pat = r"(?<!\d)1[3-9]\d{9}(?!\d)"
        idcard = "身份证号410102199203138618。"
        phone = "联系电话13812345678。"
        self.assertEqual(re.findall(pat, idcard), [],
                         "身份证号不应该命中手机号正则")
        self.assertEqual(re.findall(pat, phone), ["13812345678"])
        masked = re.sub(pat, lambda m: m.group(0)[:3] + "****" + m.group(0)[7:],
                        phone)
        self.assertEqual(masked, "联系电话138****5678。")


# ================================================================ GSXT IP 风控
class TestGsxtIpBlock(unittest.TestCase):
    """公示系统 IP 风控页的识别（风控文案变了要能及时发现）。"""

    _SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "platforms", "gsxt.py")

    def test_detect_patterns_present(self):
        with open(self._SRC, "r", encoding="utf-8") as f:
            src = f.read()
        for kw in ("当前IP请求异常", "可疑的攻击行为", "更换IP地址"):
            self.assertIn(kw, src,
                          "gsxt._detect_ip_blocked 缺少特征文案：%s" % kw)

    def test_detect_returns_bool(self):
        from types import SimpleNamespace

        from platforms.gsxt import GsxtHandler

        h = GsxtHandler.__new__(GsxtHandler)
        logs = []
        h.engine = SimpleNamespace(log=logs.append)

        class _P:
            def __init__(self, snippet):
                self.snippet = snippet

            def evaluate(self, js, arg=None):
                return self.snippet

        self.assertTrue(h._detect_ip_blocked(
            _P("当前IP请求异常，请更换IP地址进行访问")))
        self.assertTrue(any("IP 风控" in m for m in logs))
        self.assertFalse(h._detect_ip_blocked(_P("")))
        # evaluate 抛异常（页面跳转中）不能把流程打断
        class _Bad:
            def evaluate(self, js, arg=None):
                raise RuntimeError("Execution context was destroyed")
        self.assertFalse(h._detect_ip_blocked(_Bad()))


# ============================================================ 入口链 / Referer
class TestNavReferer(unittest.TestCase):
    """入口链导航必须能携带上个网站的信息（Referer）。

    瑞数 WAF 会把「无来源直达」判成异常请求：页面能开，但点查询毫无反应，
    刷新后提示「当前IP请求异常 / 您的IP最近有可疑的攻击行为」。
    """

    def test_goto_passes_referer(self):
        from core import nav
        calls = {}

        class _P:
            def goto(self, url, **kw):
                calls.update(url=url, **kw)

        nav.goto(_P(), "https://www.gsxt.gov.cn/",
                 referer="https://www.samr.gov.cn/")
        self.assertEqual(calls.get("referer"), "https://www.samr.gov.cn/")

    def test_goto_without_referer_omits_kwarg(self):
        from core import nav
        calls = {}

        class _P:
            def goto(self, url, **kw):
                calls.update(url=url, **kw)

        nav.goto(_P(), "https://www.samr.gov.cn/")
        self.assertNotIn("referer", calls)

    def test_gsxt_chain_fallback_carries_referer(self):
        from core import nav
        chain = nav.ENTRY_CHAINS["gsxt"]
        self.assertTrue(any(s.get("referer") for s in chain),
                        "gsxt 入口链的兜底直连必须带 referer")

    def test_every_site_has_default_referer(self):
        """每个站点都要有默认「上个网站」，否则裸跳必被 WAF 记异常。"""
        from core import nav
        for key in nav.ENTRY_CHAINS:
            self.assertTrue(nav.site_referer(key),
                            "%s 缺少默认 Referer" % key)

    def test_direct_chain_entries_get_referer(self):
        """入口链里「直连兜底」（无 match）必须能拿到 Referer。"""
        from core import nav
        for key, chain in nav.ENTRY_CHAINS.items():
            for step in chain:
                if not step.get("match"):
                    ref = step.get("referer") or nav.site_referer(key)
                    self.assertTrue(ref, "%s 的直连兜底没有 Referer" % key)

    def test_platform_gotos_carry_referer(self):
        """所有平台的直连导航都必须带 referer=（用户要求：所有网站都携带）。"""
        import glob
        plat_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "platforms")
        missing = []
        for path in sorted(glob.glob(os.path.join(plat_dir, "*.py"))):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            for i, line in enumerate(lines):
                s = line.strip()
                if s.startswith("#"):
                    continue
                if "nav.goto(" in s or "page.goto(" in s:
                    window = " ".join(lines[i:i + 4])
                    if "referer=" not in window:
                        missing.append("%s:%d" % (os.path.basename(path), i + 1))
        self.assertFalse(missing, "这些直连没带 Referer：%s" % missing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
