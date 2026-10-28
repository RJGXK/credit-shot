# -*- coding: utf-8 -*-
"""离线评估：信用中国验证码「预处理 + 打码题型」组合的准确率。

样本：probe_out/samples/s*.jpg（人工标注的答案写在 TRUTH 里）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageOps, ImageFilter
from core.yescaptcha import YesCaptcha
from auth.credentials import load_captcha_key

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "probe_out", "samples")

# 人工判读的结果
TRUTH = {
    "s02.jpg": "WLKM",
    "s04.jpg": "3F4T",
    "s05.jpg": "CEC1",
    "s06.jpg": "Z0Q4",
    "s07.jpg": "0TI1",
    "s08.jpg": "3DX7",
}


# ---------------- 预处理方案 ----------------
def p_raw(im):
    return im


def p_x3(im):
    return im.resize((im.width * 3, im.height * 3), Image.LANCZOS)


def p_x4(im):
    return im.resize((im.width * 4, im.height * 4), Image.LANCZOS)


def p_x4_gray(im):
    g = ImageOps.autocontrast(im.convert("L"))
    return g.resize((g.width * 4, g.height * 4), Image.LANCZOS)


def p_x4_bin(im):
    g = ImageOps.autocontrast(im.convert("L"))
    g = g.resize((g.width * 4, g.height * 4), Image.LANCZOS)
    return g.point(lambda v: 0 if v < 140 else 255)


def p_x4_bin_sharp(im):
    g = ImageOps.autocontrast(im.convert("L"))
    g = g.resize((g.width * 4, g.height * 4), Image.LANCZOS)
    g = g.point(lambda v: 0 if v < 150 else 255)
    return g.filter(ImageFilter.SMOOTH)


def p_x6_gray(im):
    g = ImageOps.autocontrast(im.convert("L"))
    return g.resize((g.width * 6, g.height * 6), Image.LANCZOS)


PRE = {
    "raw": p_raw,
    "x3": p_x3,
    "x4": p_x4,
    "x4gray": p_x4_gray,
    "x4bin": p_x4_bin,
    "x4bin_sh": p_x4_bin_sharp,
    "x6gray": p_x6_gray,
}


def to_png(im):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def run(solver, name, fn, task):
    ok = 0
    total = 0
    details = []
    for f, truth in sorted(TRUTH.items()):
        path = os.path.join(SAMPLES, f)
        if not os.path.exists(path):
            continue
        im = Image.open(path)
        data = to_png(fn(im))
        try:
            if task == "ocrbase":
                text = solver.solve_image_to_text(data)
            elif task == "async":
                text = solver.solve_image_to_text_async(data, numeric=0, case_sensitive=False)
            elif task == "muggle":
                obj = solver.create_task({"type": "ImageToTextTaskMuggle", "body":
                                          __import__("base64").b64encode(data).decode()})
                text = (obj.get("solution") or {}).get("text", "")
            else:
                text = ""
        except Exception as exc:
            text = "<%s>" % str(exc)[:30]
        total += 1
        hit = str(text).strip().lower() == truth.lower()
        ok += 1 if hit else 0
        details.append("%s:%r%s" % (f[1:3], text, "" if hit else "(错,%s)" % truth))
    print("  %-22s %d/%d  %s" % (name, ok, total, " ".join(details)))
    return ok, total


def main():
    api_key = load_captcha_key()
    solver = YesCaptcha(api_key, "cn", lambda s: None)
    tasks = sys.argv[1:] or ["ocrbase"]
    for task in tasks:
        print("\n== 题型 %s ==" % task)
        for name, fn in PRE.items():
            run(solver, "%s/%s" % (task, name), fn, task)


if __name__ == "__main__":
    main()
