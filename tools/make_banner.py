# -*- coding: utf-8 -*-
"""生成安装向导的欢迎页横幅（NSIS 的 MUI_WELCOMEFINISHPAGE_BITMAP 要 BMP）。

    python tools/make_banner.py

输出：assets/banner.bmp（164×314，NSIS 推荐的尺寸）

用 PIL 画品牌渐变底 + 图标 + 名称，深色底配浅色字，和程序图标同一套配色。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")
OUT_FILE = os.path.join(OUT_DIR, "banner.bmp")

W, H = 164, 314

BRAND_TOP = (18, 74, 155)
BRAND_BOTTOM = (8, 44, 102)
WHITE = (255, 255, 255)
ACCENT = (255, 193, 7)
LIGHT = (206, 224, 248)


def render() -> Image.Image:
    img = Image.new("RGB", (W, H), BRAND_BOTTOM)
    d = ImageDraw.Draw(img)

    # 竖向渐变
    for y in range(H):
        t = y / max(H - 1, 1)
        c = tuple(int(BRAND_TOP[i] + (BRAND_BOTTOM[i] - BRAND_TOP[i]) * t)
                  for i in range(3))
        d.line([(0, y), (W, y)], fill=c)

    # 斜向装饰带（呼应安装向导默认页的观感）
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.polygon([(0, 150), (W, 96), (W, 150), (0, 210)], fill=(0, 0, 0, 46))
    bd.polygon([(0, 232), (W, 178), (W, 210), (0, 264)], fill=(0, 0, 0, 34))
    img.paste(band, (0, 0), band)

    # 居中放程序图标（复用 app.ico 里的 64px 图）
    ico_path = os.path.join(OUT_DIR, "app.ico")
    if os.path.isfile(ico_path):
        try:
            icon = Image.open(ico_path)
            icon.size = (64, 64)
            icon = icon.convert("RGBA")
            img.paste(icon, ((W - 64) // 2, 44), icon)
        except Exception:
            pass

    # 名称文字（用系统字体；找不到就跳过，不影响安装）
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    except Exception:
        font = small = None

    if font:
        d.text((W // 2, 124), "企业信用", font=font, fill=WHITE, anchor="mm")
        d.text((W // 2, 145), "一键截图工具", font=font, fill=WHITE, anchor="mm")
        d.line([(28, 168), (W - 28, 168)], fill=ACCENT, width=2)
        d.text((W // 2, 188), "版本 2.0.0", font=small, fill=LIGHT, anchor="mm")
        d.text((W // 2, 208), "本地运行 · 不上传数据", font=small,
               fill=LIGHT, anchor="mm")

    return img


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    render().save(OUT_FILE, format="BMP")
    print("已生成横幅：%s（%d×%d）" % (OUT_FILE, W, H))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
