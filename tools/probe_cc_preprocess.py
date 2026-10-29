# -*- coding: utf-8 -*-
"""离线比对：验证码送打码服务前怎么预处理，识别率最高？

用真机存下来的三张信用中国验证码图，逐个试各种预处理，
看哪种能把字符读对（肉眼可读的正确答案已标注在 EXPECT 里）。

用法：python tools/probe_cc_preprocess.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.captcha import denoise_captcha, preprocess_captcha   # noqa: E402
from core.yescaptcha import YesCaptcha                          # noqa: E402
from auth.credentials import load_captcha_key                   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "probe_out")

CASES = [
    ("ocr_1_element.png", "C6A1"),
    ("verify_cc_1.png", "8HUT"),
    ("verify_cc_3.png", "Q9H0"),
]


def upscale(data, k, mode):
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im = im.resize((im.width * k, im.height * k), mode)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main():
    key = load_captcha_key()
    if not key:
        print("没有 API Key")
        return
    client = YesCaptcha(key, "cn", print)

    variants = [
        ("原样", lambda d: d),
        ("预处理(2x LANCZOS)", lambda d: preprocess_captcha(d)),
        ("去干扰线", lambda d: denoise_captcha(d)),
        ("去线+2x LANCZOS", lambda d: preprocess_captcha(denoise_captcha(d))),
        ("去线+3x NEAREST", lambda d: upscale(denoise_captcha(d), 3, Image.NEAREST)),
        ("3x NEAREST", lambda d: upscale(d, 3, Image.NEAREST)),
        ("3x LANCZOS", lambda d: upscale(d, 3, Image.LANCZOS)),
        ("灰度+去线+3x", lambda d: upscale(denoise_captcha(d), 3, Image.NEAREST)),
    ]

    score = {name: 0 for name, _ in variants}
    for fn, expect in CASES:
        path = os.path.join(OUT, fn)
        if not os.path.exists(path):
            print("缺少样本：%s" % fn)
            continue
        data = open(path, "rb").read()
        print("\n=== %s（肉眼应该是 %s）===" % (fn, expect))
        for name, fn2 in variants:
            try:
                d = fn2(data)
            except Exception as exc:
                print("  %-22s 预处理失败 %s" % (name, exc))
                continue
            try:
                txt = client.solve_image_to_text(d)
            except Exception as exc:
                txt = "ERR:%s" % exc
            hit = (txt or "").upper() == expect.upper()
            if hit:
                score[name] += 1
            print("  %-22s -> %-14r %s" % (name, txt, "✔" if hit else "✘"))

    print("\n===== 汇总（3 张图对了几个）=====")
    for name, _ in variants:
        print("  %-22s %d/3" % (name, score[name]))


if __name__ == "__main__":
    main()
