# -*- coding: utf-8 -*-
"""探针：拦截信用中国验证码图片请求，看服务端到底返回了什么（状态码/头/体）。

用 route.fetch() 拿到真实响应，再原样 fulfill 回页面。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_out")
os.makedirs(OUT, exist_ok=True)


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()

        def handle(route):
            try:
                resp = route.fetch(timeout=30000)
                hdr = {k: v for k, v in resp.headers.items()
                       if k.lower() in ("content-type", "content-length", "x-via-jsl",
                                        "set-cookie", "access-control-allow-origin",
                                        "cache-control", "server")}
                body = resp.body()
                print("  [route] status=%s len=%d headers=%s" % (resp.status, len(body), hdr))
                print("  [route] body head = %r" % body[:120])
                fn = os.path.join(OUT, "getverify_%d.bin" % int(time.time() * 1000))
                open(fn, "wb").write(body)
                route.fulfill(response=resp, body=body)
            except Exception as exc:
                print("  [route] 异常：%s" % exc)
                try:
                    route.continue_()
                except Exception:
                    pass

        page.route("**/getVerify*", handle)

        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")
        time.sleep(8)
        st = page.evaluate("""()=>{const i=document.querySelector('#vcodeimg');
            return i? (i.naturalWidth+'x'+i.naturalHeight):'-';}""")
        print("  最终 natural =", st)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
