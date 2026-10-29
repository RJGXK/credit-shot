# -*- coding: utf-8 -*-
"""离线比对（修正版）：验证码送打码服务前怎么放大，识别率最高？

样本来自真机（肉眼可读的正确答案标在 EXPECT 里）：
  ocr_1_element.png  C6A1
  verify_cc_1.png    8HUT
  verify_cc_3.png    Q9H0
  fetch2_orig.jpg    59IV

用法：python tools/probe_cc_modes2.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                  # noqa: E402
import io                              # noqa: E402

from core.captcha import denoise_captcha           # noqa: E402
from core.yescaptcha import YesCaptcha              # noqa: E402
from auth.credentials import load_captcha_key       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "probe_out")

CASES = [
    ("ocr_1_element.png", "C6A1"),
    ("verify_cc_1.png", "8HUT"),
    ("verify_cc_3.png", "Q9H0"),
    ("fetch2_orig.jpg", "59IV"),
]


def up(data, k, mode):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im = im.resize((im.width * k, im.height * k), mode)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def gray(data):
    im = Image.open(io.BytesIO(data)).convert("L")
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
        ("3x NEAREST", lambda d: up(d, 3, Image.NEAREST)),
        ("4x NEAREST", lambda d: up(d, 4, Image.NEAREST)),
        ("3x LANCZOS", lambda d: up(d, 3, Image.LANCZOS)),
        ("去线+3x NEAREST", lambda d: up(denoise_captcha(d), 3, Image.NEAREST)),
        ("灰度+去线+4x NEAREST", lambda d: up(denoise_captcha(gray(d)), 4, Image.NEAREST)),
    ]
    stats = {}
    for fn, expect in CASES:
        path = os.path.join(OUT, fn)
        if not os.path.exists(path):
            continue
        data = open(path, "rb").read()
        print("\n=== %s（应为 %s）===" % (fn, expect))
        for vname, vf in variants:
            try:
                d = vf(data)
            except Exception as exc:
                print("  %-20s 预处理失败 %s" % (vname, exc))
                continue
            for tname, fn2 in (("同步", client.solve_image_to_text),
                               ("异步", client.solve_image_to_text_async)):
                try:
                    txt = fn2(d)
                except Exception as exc:
                    txt = "ERR:%s" % str(exc)[:24]
                k = "%s+%s" % (vname, tname)
                st = stats.setdefault(k, [0, 0])
                st[0] += 1
                ok = (txt or "").upper() == expect.upper()
                if ok:
                    st[1] += 1
                print("  %-20s %-4s -> %-16r %s" % (vname, tname, txt, "✔" if ok else "✘"))
    print("\n===== 汇总 =====")
    for k, v in sorted(stats.items(), key=lambda x: -x[1][1]):
        print("  %-26s 读对 %d/%d" % (k, v[1], v[0]))


if __name__ == "__main__":
    main()
