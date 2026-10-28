# -*- coding: utf-8 -*-
"""实验：把信用中国验证码里的「干扰线」去掉，看哪种预处理能让识别变准。

只输出图片（拼图），供人工看；OCR 评测见 bench_ocr.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageOps, ImageFilter

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "probe_out", "samples")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "pre")

FILES = ["s02.jpg", "s04.jpg", "s05.jpg", "s06.jpg", "s07.jpg", "s08.jpg"]


def open3(im):
    """形态学开运算：去掉细的干扰线，保留粗的字符笔画。"""
    g = im.convert("L")
    return g.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))


def desat(im):
    """按饱和度挑出「彩色字符」，灰白的干扰线丢掉。"""
    hsv = im.convert("HSV")
    s = hsv.split()[1]
    mask = s.point(lambda v: 255 if v > 55 else 0)
    black = Image.new("L", im.size, 0)
    white = Image.new("L", im.size, 255)
    return Image.composite(black, white, mask)


def open3_bin(im):
    g = open3(im)
    g = ImageOps.autocontrast(g)
    return g.point(lambda v: 0 if v < 150 else 255)


def desat_bin(im):
    g = desat(im)
    g = ImageOps.autocontrast(g)
    return g.point(lambda v: 0 if v < 150 else 255)


def open3_desat(im):
    """先按饱和度挑字符，再对字符做开运算。"""
    hsv = im.convert("HSV")
    s = hsv.split()[1]
    mask = s.point(lambda v: 255 if v > 55 else 0)
    g = open3(im)
    g = ImageOps.autocontrast(g)
    g = g.point(lambda v: 0 if v < 150 else 255)
    white = Image.new("L", g.size, 255)
    return Image.composite(g, white, mask)


VARIANTS = [
    ("raw", lambda im: im.convert("L")),
    ("open3", open3),
    ("open3bin", open3_bin),
    ("desat", desat),
    ("desatbin", desat_bin),
    ("open3desat", open3_desat),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in VARIANTS:
        rows = []
        for f in FILES:
            p = os.path.join(SAMPLES, f)
            if not os.path.exists(p):
                continue
            im = Image.open(p)
            out = fn(im)
            out = out.resize((out.width * 4, out.height * 4), Image.LANCZOS)
            rows.append(out)
        if not rows:
            continue
        w = max(r.width for r in rows)
        h = sum(r.height for r in rows)
        canvas = Image.new("L", (w, h), 255)
        y = 0
        for r in rows:
            canvas.paste(r, (0, y))
            y += r.height
        fn_out = os.path.join(OUT, "%s.png" % name)
        canvas.save(fn_out)
        print("%-12s -> %s (%s)" % (name, fn_out, canvas.size))


if __name__ == "__main__":
    main()
