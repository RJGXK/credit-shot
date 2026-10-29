# -*- coding: utf-8 -*-
"""验证验证码「刷新重试」机制（用户反馈：第一次不显示，刷新几次才显示）。

用一个假页面模拟真实场景：
  · 第 1、2 次截到的图是**白板**（纯色）；
  · 第 3 次点「刷新」后出图，内容是 4 个字符。
断言：程序自动刷新重试后能拿到识别文本，而不是停在空结果。

同时验证 image_looks_blank 的判定。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.captcha import image_looks_blank


def _make_png(color, size=(120, 40)):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_text_png():
    """造一张有内容的图（深色文字块），不是纯色。"""
    from PIL import Image, ImageDraw
    import io
    img = Image.new("RGB", (120, 40), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(4):
        x = 10 + i * 28
        d.rectangle([x, 10, x + 18, 30], fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_blank_detection():
    blank = _make_png((255, 255, 255))
    content = _make_text_png()
    assert image_looks_blank(blank) is True, "纯白图应判为空白"
    assert image_looks_blank(content) is False, "有内容的图不应判为空白"
    print("✔ 空白图判定正确")


class _FakeImg:
    """模拟验证码 <img>：前两次截图是白板，刷新后才有内容。"""

    def __init__(self, owner):
        self.owner = owner

    def screenshot(self, timeout=None):
        self.owner["shots"] += 1
        if self.owner["shots"] < 3:
            return _make_png((250, 250, 250))
        return _make_text_png()


class _FakeTarget:
    """模拟验证码弹层：点刷新会切换状态。"""

    def __init__(self):
        self.state = {"shots": 0, "refresh": 0}

    def query_selector(self, sel):
        if sel in ("img", "#vcodeimg"):
            return _FakeImg(self.state)
        return None

    def evaluate(self, js, arg=None):
        # 读「验证码错误提示」的脚本必须返回空串（表示没有错误）
        if "errortip" in js:
            return ""
        # 点提交按钮的脚本要返回 "CLICK:xxx"（注意：这段脚本里也有 arg.texts，
        # 必须排在 "arg.text" 之前判断，否则会被当成填框脚本）
        if "hit.click()" in js:
            return "CLICK:验证"
        # 填验证码输入框的脚本要返回 "OK"
        if "arg.text" in js or "arg.scope" in js:
            return "OK"
        if "getElementById" in js and "captcha" in js:
            return "OK"
        if "querySelectorAll('input" in js:
            return "OK"
        if "createElement" in js:
            return "OK"
        return True

    def query_selector_all(self, sel):
        return []


def test_refresh_retry():
    from core.captcha import CaptchaSolver

    logs = []
    target = _FakeTarget()

    class _Solver:
        def solve_captcha_image_element(self, element, timeout=20):
            # 模拟：截图是白板时给不出结果
            return "8K3P" if target.state["shots"] >= 3 else ""

    solver = CaptchaSolver.__new__(CaptchaSolver)
    solver.api_key = "x"
    solver.region = "cn"
    solver.log = logs.append
    solver._client = _Solver()

    ok = solver.solve_image_captcha(target, img_selector="#vcodeimg",
                                   scope_selector=".vcodepop")
    print("  截图次数:", target.state["shots"])
    assert ok is True, "刷新重试后应该识别成功"
    assert target.state["shots"] >= 3, "应该至少重试到第 3 次"
    assert any("刷新" in m for m in logs), "日志里应说明做了刷新重试"
    print("✔ 刷新重试机制生效")


def main():
    test_blank_detection()
    test_refresh_retry()
    print("\n全部通过")


if __name__ == "__main__":
    main()
