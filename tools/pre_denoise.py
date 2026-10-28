# -*- coding: utf-8 -*-
"""实验3：按「笔画粗细」去掉干扰线（纯 Python，不引入新依赖）。

原理
----
干扰线是 1px 宽的斜线/曲线；字符笔画在水平或垂直方向上至少有 3px 连通。
判据：像素若处在「长度>=3 的水平段」或「长度>=3 的垂直段」里，就认为是字符笔画；
      再把掩码膨胀 1px，把贴着笔画的斜线段（如 Z 的斜杠）补回来。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFilter, ImageChops

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "probe_out", "samples")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "pre")
FILES = ["s02.jpg", "s04.jpg", "s05.jpg", "s06.jpg", "s07.jpg", "s08.jpg"]


def denoise(im, thr=150, dilate=1):
    """返回 (掩码图 L, 干净图 L)。"""
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    dark = [[1 if px[x, y] < thr else 0 for x in range(w)] for y in range(h)]

    keep = [[0] * w for _ in range(h)]
    for y in range(h):
        row = dark[y]
        for x in range(w):
            if not row[x]:
                continue
            # 水平连续 >=3
            a = x
            while a - 1 >= 0 and row[a - 1]:
                a -= 1
            b = x
            while b + 1 < w and row[b + 1]:
                b += 1
            if b - a + 1 >= 3:
                keep[y][x] = 1
                continue
            # 垂直连续 >=3
            c = y
            while c - 1 >= 0 and dark[c - 1][x]:
                c -= 1
            d = y
            while d + 1 < h and dark[d + 1][x]:
                d += 1
            if d - c + 1 >= 3:
                keep[y][x] = 1

    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if keep[y][x]:
                mp[x, y] = 255
    if dilate:
        mask = mask.filter(ImageFilter.MaxFilter(3))
    black = Image.new("L", (w, h), 0)
    white = Image.new("L", (w, h), 255)
    clean = Image.composite(black, white, mask)
    return mask, clean


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for f in FILES:
        p = os.path.join(SAMPLES, f)
        if not os.path.exists(p):
            continue
        im = Image.open(p)
        mask, clean = denoise(im)
        out = clean.resize((clean.width * 4, clean.height * 4), Image.LANCZOS)
        rows.append(out)
        clean.save(os.path.join(OUT, "dn_%s.png" % f.replace(".jpg", "")))
    if rows:
        w = max(r.width for r in rows)
        h = sum(r.height for r in rows)
        canvas = Image.new("L", (w, h), 255)
        y = 0
        for r in rows:
            canvas.paste(r, (0, y))
            y += r.height
        canvas.save(os.path.join(OUT, "denoise.png"))
        print("->", os.path.join(OUT, "denoise.png"), canvas.size)


if __name__ == "__main__":
    main()
