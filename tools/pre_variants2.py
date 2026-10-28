# -*- coding: utf-8 -*-
"""实验2：更细致地去干扰线。

思路：
  · 干扰线 = 细（1~2px）+ 灰白（低饱和）
  · 字符   = 粗（2~3px）+ 有颜色（可能饱和也可能很深）
所以 mask = 「粗笔画」 ∪ 「高饱和笔画」。
只输出拼图，供人工判断。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageOps, ImageFilter, ImageChops

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "probe_out", "samples")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "pre")
FILES = ["s02.jpg", "s04.jpg", "s05.jpg", "s06.jpg", "s07.jpg", "s08.jpg"]


def _mask_to_bw(mask):
    black = Image.new("L", mask.size, 0)
    white = Image.new("L", mask.size, 255)
    return Image.composite(black, white, mask)


def _color_mask(im, thr=55):
    s = im.convert("HSV").split()[1]
    return s.point(lambda v: 255 if v > thr else 0)


def _thick_mask(im, k=3, thr=140):
    g = im.convert("L")
    dil = g.filter(ImageFilter.MaxFilter(k))
    return dil.point(lambda v: 255 if v < thr else 0)


def v_max3(im):
    g = im.convert("L").filter(ImageFilter.MaxFilter(3))
    g = ImageOps.autocontrast(g)
    return g.point(lambda v: 0 if v < 150 else 255)


def v_max3_color(im):
    """RGB 上做膨胀：白底吃掉细灰线，同时保留字符颜色。"""
    return im.filter(ImageFilter.MaxFilter(3))


def v_max5(im):
    g = im.convert("L").filter(ImageFilter.MaxFilter(5))
    g = ImageOps.autocontrast(g)
    return g.point(lambda v: 0 if v < 150 else 255)


def v_union3(im):
    m = ImageChops.lighter(_thick_mask(im, 3), _color_mask(im))
    return _mask_to_bw(m)


def v_union5(im):
    m = ImageChops.lighter(_thick_mask(im, 5), _color_mask(im))
    return _mask_to_bw(m)


def v_union3_thr(im):
    m = ImageChops.lighter(_thick_mask(im, 3, 120), _color_mask(im, 40))
    return _mask_to_bw(m)


def v_union3_open(im):
    """union 再补一次开运算，压掉残留细线。"""
    m = ImageChops.lighter(_thick_mask(im, 3), _color_mask(im))
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return _mask_to_bw(m)


VARIANTS = [
    ("max3", v_max3),
    ("max3color", v_max3_color),
    ("max5", v_max5),
    ("union3", v_union3),
    ("union5", v_union5),
    ("union3thr", v_union3_thr),
    ("union3open", v_union3_open),
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
            out = fn(im).convert("L")
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
        canvas.save(os.path.join(OUT, "%s.png" % name))
        print("%-12s -> %s" % (name, os.path.join(OUT, "%s.png" % name)))


if __name__ == "__main__":
    main()
