# -*- coding: utf-8 -*-
"""探针6：ORB 拦掉的是「渲染」，网络层还能不能拿到验证码**原图字节**？

背景（已实测）：
  · 验证码图挂在跨域 public.creditchina.gov.cn；
  · 浏览器 <img> 加载经常被 Edge 的 ORB 拦掉（net::ERR_BLOCKED_BY_ORB），
    页面上是破图（naturalWidth=0）；
  · 自己 fetch 同一个 src 会拿到**另一张**图（会把 session 里的验证码顶掉），不能用；
  · 但**浏览器自己那次请求的响应体**应该还在网络层里 ——
    如果能拿到，就是原图字节，且不产生任何额外请求、不顶掉验证码。

用法：python tools/probe_cc_net2.py [公司名]
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver           # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        hits = []
        fails = []

        def on_response(resp):
            try:
                u = resp.url or ""
                if "getverify" not in u.lower():
                    return
                rec = {"url": u, "status": resp.status,
                       "ct": resp.headers.get("content-type"),
                       "len": 0, "md5": "", "body": b"", "err": ""}
                try:
                    body = resp.body()
                    rec["body"] = body
                    rec["len"] = len(body)
                    rec["md5"] = hashlib.md5(body).hexdigest()[:10]
                except Exception as exc:
                    rec["err"] = str(exc)[:90]
                hits.append(rec)
            except Exception:
                pass

        def on_failed(req):
            try:
                if "getverify" in (req.url or "").lower():
                    fails.append((req.url, str(req.failure)))
            except Exception:
                pass

        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        page.on("response", on_response)
        page.on("requestfailed", on_failed)

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
        time.sleep(6)

        print("\n===== getVerify 响应 =====")
        for i, h in enumerate(hits):
            print("  #%d status=%s ct=%s len=%s md5=%s %s"
                  % (i + 1, h["status"], h["ct"], h["len"], h["md5"], h["err"]))
            if h["body"]:
                fn = os.path.join(OUT, "net2_%d.bin" % (i + 1))
                open(fn, "wb").write(h["body"])
                print("      已存 %s" % fn)
        print("===== requestfailed =====")
        for u, why in fails:
            print("  %s :: %s" % (u[-50:], why))

        st = page.evaluate(
            """()=>{const i=document.querySelector('#vcodeimg');
                 return {nat:i?((i.naturalWidth||0)+'x'+(i.naturalHeight||0)):'',
                         src:i?((i.currentSrc||i.src||'').slice(-30)):''};}""")
        print("\n页面显示状态：%s" % st)

        solver = CaptchaSolver("", "cn", print)
        scope = page.query_selector(".vcodepop")
        shot, how, meta = solver._capture_captcha(page, "#vcodeimg", scope, ".vcodepop")
        print("元素截图：%s" % ("%d 字节" % len(shot) if shot else "没取到"))
        if shot:
            open(os.path.join(OUT, "net2_shot.png"), "wb").write(shot)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
