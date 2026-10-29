# -*- coding: utf-8 -*-
"""探针：信用中国验证码识别不准 —— 到底该喂什么图给打码服务？

对比三种喂法（同一张验证码）：
  1. 元素截图（现状）：浏览器把 95x25 的原图拉伸到 177x63，边缘被插值糊掉；
  2. canvas 取**原始像素**（naturalWidth x naturalHeight，无拉伸、无糊）；
  3. 原图 + 最近邻放大 3 倍（笔画更清晰）。

每种都试两种题型：
  · ImageToTextTaskOcrBase（同步，2 点，现用）
  · ImageToTextTask（异步，4 点，官方说识别率更高）

用法：python tools/probe_cc_ocr.py [公司名]
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver           # noqa: E402
from auth.credentials import load_captcha_key    # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

CANVAS_JS = """
(sel)=>{
  const img=document.querySelector(sel);
  if(!img) return null;
  const nw=img.naturalWidth, nh=img.naturalHeight;
  if(!nw||!nh) return null;
  const c=document.createElement('canvas');
  c.width=nw; c.height=nh;
  c.getContext('2d').drawImage(img,0,0,nw,nh);
  try{ return {png:c.toDataURL('image/png'), w:nw, h:nh}; }
  catch(e){ return {err:String(e), w:nw, h:nh}; }
}
"""


def upscale_nearest(data, k=3):
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im = im.resize((im.width * k, im.height * k), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    key = load_captcha_key()
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称')"
                  " && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn');"
                      " if(b) b.click();}")
        deadline = time.time() + 25
        while time.time() < deadline:
            shown = page.evaluate("()=>{const p=document.querySelector('.vcodepop');"
                                  "return !!(p&&getComputedStyle(p).display!=='none');}")
            if shown:
                break
            time.sleep(1.0)
        time.sleep(2)

        solver = CaptchaSolver(key, "cn", print)
        scope = page.query_selector(".vcodepop")

        # 1) 元素截图（现状）
        raw, how, meta = solver._capture_captcha(page, "#vcodeimg", scope, ".vcodepop")
        if not raw:
            print("⚠ 没取到元素截图，本轮跳过")
            return
        open(os.path.join(OUT, "ocr_1_element.png"), "wb").write(raw)

        # 2) canvas 原始像素
        cj = page.evaluate(CANVAS_JS, "#vcodeimg")
        orig = b""
        if cj and cj.get("png"):
            b64 = cj["png"].split(",", 1)[1]
            orig = base64.b64decode(b64)
            open(os.path.join(OUT, "ocr_2_canvas.png"), "wb").write(orig)
            print("canvas 原始像素：%dx%d，%d 字节" % (cj.get("w", 0), cj.get("h", 0),
                                                    len(orig)))
        else:
            print("canvas 取原始像素失败：%s" % (cj or {}).get("err"))
        if orig:
            up = upscale_nearest(orig, 3)
            open(os.path.join(OUT, "ocr_3_nearest3x.png"), "wb").write(up)

        print("\n元素截图 %d 字节 / 原图 %d 字节" % (len(raw), len(orig)))

        client = solver.client()
        cases = [("元素截图(现状)", raw),
                 ("canvas 原图", orig),
                 ("原图最近邻3x", upscale_nearest(orig, 3) if orig else b"")]
        for name, data in cases:
            if not data:
                continue
            t0 = time.time()
            try:
                txt = client.solve_image_to_text(data)
            except Exception as exc:
                txt = "ERR:%s" % exc
            t1 = time.time() - t0
            try:
                txt2 = client.solve_image_to_text_async(data)
            except Exception as exc:
                txt2 = "ERR:%s" % exc
            print("  %-16s 同步题型=%-14r  异步题型=%-14r" % (name, txt, txt2))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
