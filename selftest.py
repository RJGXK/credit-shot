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
        self.assertEqual(sent["body"]["task"]["type"], "ImageToTextTaskOcrBase")
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

    def evaluate(self, js, arg=None):
        if "document.body" in js:
            return self.text
        # gsxt 填值脚本（一次填 UserName + gsxtp）
        if "set('UserName'" in js:
            frame = self.frames[0]
            frame.filled.append(arg)
            return "OK/OK"
        return True


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
