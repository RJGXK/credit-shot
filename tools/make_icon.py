# -*- coding: utf-8 -*-
"""生成程序图标 assets/app.ico（与界面配色一致）。

    python tools/make_icon.py

不依赖外部素材：直接用 PIL 画出来，输出多尺寸 ICO。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")
OUT_FILE = os.path.join(OUT_DIR, "app.ico")

# 与 web/static/css/app.css 里的品牌色一致
BRAND_TOP = (18, 74, 155)
BRAND_BOTTOM = (11, 58, 128)
WHITE = (255, 255, 255)
ACCENT = (255, 193, 7)


def render(size: int) -> Image.Image:
    """画一张 size×size 的图标：深蓝圆角底 + 白色文档 + 黄色放大镜。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角方形底（竖向渐变）
    radius = int(size * 0.22)
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(size - 1, 1)
        color = tuple(int(BRAND_TOP[i] + (BRAND_BOTTOM[i] - BRAND_TOP[i]) * t)
                      for i in range(3)) + (255,)
        gd.line([(0, y), (size, y)], fill=color)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # 文档主体
    dw = int(size * 0.42)
    dh = int(size * 0.54)
    dx = int(size * 0.16)
    dy = int(size * 0.19)
    d.rounded_rectangle([dx, dy, dx + dw, dy + dh],
                        radius=int(size * 0.05), fill=WHITE)

    # 文档上的三行文字
    line_h = max(1, int(size * 0.035))
    pad = int(dw * 0.16)
    for i in range(3):
        y = dy + int(dh * (0.28 + i * 0.22))
        w = dw - pad * 2 - (int(dw * 0.22) if i == 2 else 0)
        d.rounded_rectangle([dx + pad, y, dx + pad + w, y + line_h],
                            radius=line_h // 2,
                            fill=(150, 165, 190, 255))

    # 放大镜（黄色圈 + 深色手柄）
    r = int(size * 0.17)
    cx = int(size * 0.70)
    cy = int(size * 0.66)
    ring = max(2, int(size * 0.055))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=ring)
    hx, hy = cx + r * 0.72, cy + r * 0.72
    d.line([hx, hy, hx + r * 0.85, hy + r * 0.85],
           fill=ACCENT, width=ring)
    d.ellipse([hx + r * 0.6, hy + r * 0.6, hx + r * 1.05, hy + r * 1.05],
              fill=ACCENT)

    return img


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(s) for s in sizes]
    # ico 要求至少含 256，大图放第一个
    frames[0] = render(256)
    frames[0].save(OUT_FILE, format="ICO",
                   sizes=[(s, s) for s in sizes])
    print("已生成图标：%s" % OUT_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
