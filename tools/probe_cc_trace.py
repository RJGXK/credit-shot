# -*- coding: utf-8 -*-
"""探针：追踪信用中国 verify 接口的请求顺序，弄清「哪个验证码才是当前有效的」。

关注两类请求：
  · public.creditchina.gov.cn/private-api/verify/getVerify   —— 生成验证码
  · www.creditchina.gov.cn/.../verify...                      —— 提交校验
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav
from core.yescaptcha import YesCaptcha
from auth.credentials import load_captcha_key

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
T0 = [0.0]


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    api_key = load_captcha_key()
    solver = YesCaptcha(api_key, "cn", lambda s: None)
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
        T0[0] = time.time()

        def on_req(r):
            if "verify" in r.url.lower() or "captcha" in r.url.lower():
                print("  [%6.2fs] REQ %s %s" % (time.time() - T0[0], r.method, r.url[:110]))

        def on_resp(r):
            if "verify" in r.url.lower() or "captcha" in r.url.lower():
                print("  [%6.2fs] RES %s %s" % (time.time() - T0[0], r.status, r.url[:110]))

        page.on("request", on_req)
        page.on("response", on_resp)

        res = nav.goto_via_landing(page, "creditchina", log=lambda s: None, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=lambda s: None)
        page.wait_for_timeout(3500)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            page.wait_for_timeout(600)
        print("\n-- 点查询 --")
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")
        page.wait_for_timeout(4000)

        for rnd in (1, 2):
            print("\n-- 第 %d 轮 --" % rnd)
            st = page.evaluate("""()=>{const i=document.querySelector('#vcodeimg');
                return {nat: i?(i.naturalWidth+'x'+i.naturalHeight):'-', src: i?i.src:''};}""")
            print("  img natural=%s" % st["nat"])
            src = st["src"]
            print("  API 取图 …")
            resp = page.request.get(src, headers={"Accept": "image/*,*/*;q=0.8",
                                                  "Referer": "https://www.creditchina.gov.cn/"})
            body = resp.body()
            print("  API status=%s ct=%s len=%d" % (resp.status, resp.headers.get("content-type"), len(body)))
            if resp.status != 200:
                break
            text = solver.solve_image_to_text(body)
            print("  识别=%r" % text)
            page.evaluate("""(t)=>{const e=document.getElementById('vcode'); e.focus();
                const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                s.call(e,t); e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));}""", text)
            page.wait_for_timeout(500)
            print("  点【验证】…")
            page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm'); if(b) b.click();}")
            page.wait_for_timeout(3500)
            st2 = page.evaluate("""()=>{const t=document.querySelector('.vcodepop .errortip');
                const p=document.querySelector('.vcodepop');
                const ck=(document.cookie.match(/(?:^|;\\s*)vcode=([^;]*)/)||[])[1]||'';
                return {tip: t?(t.innerText||'').trim():'', shown: !!(t&&getComputedStyle(t).display!=='none'),
                        pop: !!(p&&getComputedStyle(p).display!=='none'), cookie: ck};}""")
            print("  提交后 tip=%r shown=%s pop=%s cookie=%r"
                  % (st2["tip"], st2["shown"], st2["pop"], st2["cookie"]))
            if st2["cookie"] == "1" or not st2["pop"]:
                print("  ==> 通过")
                break
            print("  点【看不清? 换一张】…")
            page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                          " if(s) s.click();}")
            page.wait_for_timeout(2500)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
