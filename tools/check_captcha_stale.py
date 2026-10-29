# -*- coding: utf-8 -*-
"""验证码「陈旧图」回归测试（用户反馈：信用中国总是输入识别到的上一个验证码）。

场景 A（站点不换图）：点「换一张」之后浏览器里还是**同一张图**。
       期望：程序认出「还是上一张」，**不再提交**同一张图，
             避免把上一个验证码再送一次给站点。

场景 B（站点正常换图）：点「换一张」之后图确实变了。
       期望：每一轮提交的都是**当轮那张新图**的识别结果。

场景 C（识别期间站点换了图）：识别还没回来，站点就把图换了。
       期望：本次识别结果作废，不提交，换图重来。

跑法：python tools/check_captcha_stale.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.captcha import CaptchaSolver, image_fingerprint  # noqa: E402


def _png(seed):
    """造一张内容随 seed 变化的图（不同 seed -> 不同 MD5）。"""
    from PIL import Image, ImageDraw
    import io
    buf = io.BytesIO()
    img = Image.new("RGB", (120, 40), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(4):
        x = 8 + i * 28
        d.rectangle([x, 6 + (seed % 7), x + 16, 32 - (seed % 5)], fill=(20, 20, 20))
    img.save(buf, format="PNG")
    return buf.getvalue()


class _Img:
    """假的验证码 <img>。"""

    def __init__(self, owner):
        self.owner = owner

    def screenshot(self, timeout=None):
        self.owner["shots"] += 1
        return self.owner["images"][self.owner["cur"]]

    def get_attribute(self, name):
        if name == "src":
            return self.owner["srcs"][self.owner["cur"]]
        return None


class _Page:
    """假页面：模拟「换一张」是否真的换了图。"""

    def __init__(self, images, change_on_refresh=True, swap_during_solve=False):
        self.state = {"cur": 0, "shots": 0, "refresh": 0, "submit": 0,
                      "images": images,
                      "srcs": ["/getVerify?_v=%d" % i for i in range(len(images))],
                      "change_on_refresh": change_on_refresh,
                      "swap_during_solve": swap_during_solve,
                      "solved": 0}

    # ---- Playwright 兼容接口 ----
    def query_selector(self, sel):
        return _Img(self.state) if sel in ("img", "#vcodeimg") else None

    def query_selector_all(self, sel):
        return [_Img(self.state)] if sel in ("img", "#vcodeimg") else []

    def evaluate(self, js, arg=None):
        st = self.state
        # 1) 图片状态探测（_img_state）
        if "arg.sel" in js:
            return {"src": st["srcs"][st["cur"]],
                    "ok": True, "vis": True, "index": 0}
        # 2) 错误提示读取
        if "errortip" in js:
            return "验证码错误，请输入正确验证码!"
        # 3) 点提交（这段脚本里也有 arg.texts，必须排在 "arg.text" 前面判断）
        if "hit.click()" in js:
            st["submit"] += 1
            return "CLICK:验证"
        # 4) 填验证码输入框
        if "arg.text" in js:
            return "OK"
        # 5) 点「换一张」
        if "cands" in js:
            st["refresh"] += 1
            if st["change_on_refresh"] and st["cur"] + 1 < len(st["images"]):
                st["cur"] += 1
            return "CLICK:refresh"
        # 6) 截图前的坐标归一化 / 还原
        if "__csRestores" in js:
            return {"x": 10, "y": 20, "width": 120, "height": 40}
        return None


def _make_solver(page, recognized):
    """构造一个 CaptchaSolver，识别结果由 recognized 回调给出。"""
    logs = []

    class _Solver:
        def solve_image_to_text(self, data):
            # 场景 C：识别过程中站点把图换掉
            if page.state["swap_during_solve"] and page.state["solved"] == 0:
                page.state["solved"] += 1
                page.state["cur"] = min(page.state["cur"] + 1,
                                        len(page.state["images"]) - 1)
            return recognized(page.state["cur"], data)

    s = CaptchaSolver.__new__(CaptchaSolver)
    s.api_key = "x"
    s.region = "cn"
    s.log = logs.append
    s._client = _Solver()
    s.should_stop = None
    return s, logs


def case_a_stale_image_not_submitted_twice():
    """场景 A：换图后还是同一张 -> 同一张图只允许提交一次。"""
    same = _png(1)
    images = [same, same, same]
    page = _Page(images, change_on_refresh=False)
    submitted = []

    def recognized(idx, data):
        submitted.append(image_fingerprint(data))
        return "ABCD"

    solver, logs = _make_solver(page, recognized)
    ok = solver.solve_image_captcha(page, img_selector="#vcodeimg",
                                    scope_selector=".vcodepop", tries=3)
    assert ok is False, "站点一直不换图时不该判定为通过"
    assert page.state["submit"] <= 1, \
        "同一张图提交了 %d 次，应该最多 1 次" % page.state["submit"]
    assert any("没有变化" in m for m in logs), \
        "日志里应说明「图片没有变化」：%s" % logs
    print("✔ 场景A：同一张图只提交一次（submit=%d）" % page.state["submit"])


def case_b_new_image_each_round():
    """场景 B：换图正常 -> 每一轮提交的都是当轮那张新图。"""
    images = [_png(1), _png(2), _png(3)]
    page = _Page(images, change_on_refresh=True)
    seen = []

    def recognized(idx, data):
        seen.append((idx, image_fingerprint(data)))
        return "ABCD"

    solver, logs = _make_solver(page, recognized)
    solver.solve_image_captcha(page, img_selector="#vcodeimg",
                               scope_selector=".vcodepop", tries=3)
    assert page.state["submit"] >= 2, "应该提交了多轮"
    fps = [f for _, f in seen]
    assert len(set(fps)) == len(fps), "每轮识别的图必须各不相同：%s" % fps
    print("✔ 场景B：每轮都是新图（提交 %d 次，指纹 %s）"
          % (page.state["submit"], fps))


def case_c_swap_during_solve_discarded():
    """场景 C：识别期间站点换了图 -> 本次结果作废，不提交。"""
    images = [_png(1), _png(2), _png(3)]
    page = _Page(images, change_on_refresh=True, swap_during_solve=True)
    solver, logs = _make_solver(page, lambda idx, data: "ABCD")
    solver.solve_image_captcha(page, img_selector="#vcodeimg",
                               scope_selector=".vcodepop", tries=3)
    assert any("作废" in m for m in logs), \
        "日志里应说明识别结果作废：%s" % logs
    print("✔ 场景C：识别期间换图 -> 结果作废并重来")


def main():
    case_a_stale_image_not_submitted_twice()
    case_b_new_image_each_round()
    case_c_swap_during_solve_discarded()
    print("\n全部通过")


if __name__ == "__main__":
    main()
