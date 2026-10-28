# -*- coding: utf-8 -*-
"""探针：抓 信用中国 #vcodeimg 的网络请求，看 getVerify 到底返回了什么。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
        page.on("response", lambda r: print("  [resp] %s %s" % (r.status, r.url[:110]))
                if "verify" in r.url.lower() or "captcha" in r.url.lower() else None)
        page.on("requestfailed", lambda r: print("  [fail] %s :: %s"
                % (r.url[:110], (r.failure or ""))))

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

        for i in range(20):
            time.sleep(1.0)
            st = page.evaluate("""()=>{const i=document.querySelector('#vcodeimg');
                return {nat: i? (i.naturalWidth+'x'+i.naturalHeight):'-',
                        comp: i? !!i.complete:false,
                        src: i? (i.src||''):''};}""")
            print("  t=%ds nat=%s complete=%s" % (i + 1, st["nat"], st["comp"]))
            if st["nat"] != "0x0" and st["nat"] != "-":
                break

        # 手动换一张，看新请求
        print("点「换一张」…")
        page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                      " if(s) s.click();}")
        for i in range(10):
            time.sleep(1.0)
            st = page.evaluate("""()=>{const i=document.querySelector('#vcodeimg');
                return {nat: i? (i.naturalWidth+'x'+i.naturalHeight):'-',
                        comp: i? !!i.complete:false,
                        src: i? (i.src||''):''};}""")
            print("  t=%ds nat=%s complete=%s src=%s" % (i + 1, st["nat"], st["comp"], st["src"][-30:]))
            if st["nat"] != "0x0":
                break
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
