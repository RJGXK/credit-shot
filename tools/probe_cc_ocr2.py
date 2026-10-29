# -*- coding: utf-8 -*-
"""探针2：找出喂给打码服务的**正确姿势**。

同一张验证码，比对：
  A. 元素截图（现状，浏览器把原图拉伸放大 + 插值）
  B. 抓网络响应拿到的**原始字节**（浏览器还没动过它）
  C. B 的最近邻放大 3 倍
  D. A 去干扰线
  E. B 去干扰线
  F. 同一张图连发 3 次（看 OCR 是否稳定，判断能不能用多数表决）

用法：python tools/probe_cc_ocr2.py [公司名]
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver, denoise_captcha, preprocess_captcha  # noqa: E402
from auth.credentials import load_captcha_key    # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)


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
        captured = []

        def on_response(resp):
            try:
                u = resp.url or ""
                if ("getVerify" in u or "captcha" in u.lower()
                        or "vcode" in u.lower()):
                    body = resp.body()
                    if len(body) > 200:
                        captured.append((u, body))
            except Exception:
                pass

        page.on("response", on_response)

        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
            page.on("response", on_response)
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
        time.sleep(3)

        print("\n-- 抓到 %d 个验证码图片响应 --" % len(captured))
        orig = b""
        for u, b in captured:
            print("   %s  %d 字节" % (u[-56:], len(b)))
            if b[:4] in (b"\x89PNG",) or b[:2] == b"\xff\xd8":
                orig = b
        if orig:
            open(os.path.join(OUT, "ocr2_orig_net.png"), "wb").write(orig)
            from PIL import Image
            import io as _io
            im = Image.open(_io.BytesIO(orig))
            print("   原始图片尺寸：%s" % (im.size,))

        solver = CaptchaSolver(key, "cn", print)
        scope = page.query_selector(".vcodepop")
        shot, how, meta = solver._capture_captcha(page, "#vcodeimg", scope, ".vcodepop")
        if shot:
            open(os.path.join(OUT, "ocr2_element.png"), "wb").write(shot)

        client = solver.client()
        cases = []
        if shot:
            cases.append(("A 元素截图", shot))
            cases.append(("A+去干扰线", denoise_captcha(shot)))
        if orig:
            cases.append(("B 网络原图", orig))
            cases.append(("C 原图最近邻3x", upscale_nearest(orig, 3)))
            cases.append(("E 原图去干扰线", denoise_captcha(orig)))
            cases.append(("E+原图去线+3x", upscale_nearest(denoise_captcha(orig), 3)))
        for name, data in cases:
            try:
                txt = client.solve_image_to_text(data)
            except Exception as exc:
                txt = "ERR:%s" % exc
            print("  %-18s -> %r" % (name, txt))

        # F. 稳定性：同一张图连发 3 次
        if shot:
            outs = []
            for _ in range(3):
                try:
                    outs.append(client.solve_image_to_text(shot))
                except Exception as exc:
                    outs.append("ERR")
            print("  F 同一张图连发3次: %s" % outs)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
