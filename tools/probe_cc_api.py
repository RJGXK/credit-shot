# -*- coding: utf-8 -*-
"""探针：绕过 ORB，直接用 Playwright 的 APIRequestContext 取验证码图片字节。

背景：信用中国的验证码图挂在 public.creditchina.gov.cn，
<img> 直连会被 Edge 的 ORB 拦掉（net::ERR_BLOCKED_BY_ORB），图永远显示不出来。
page.request 走的是同一套 Cookie、但不是浏览器渲染管线，可以拿到原始字节。

要验证：
1. page.request.get(img_src) 拿到的是不是图片（Content-Type / PNG 头）；
2. 拿到的字节送去打码服务，填入 #vcode 后点 a.confirm 能不能通过（cookie vcode=1）。
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
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_out")
os.makedirs(OUT, exist_ok=True)


def state(page):
    return page.evaluate("""()=>{
      const pop=document.querySelector('.vcodepop');
      const img=document.querySelector('#vcodeimg');
      const tip=document.querySelector('.vcodepop .errortip');
      const inp=document.querySelector('#vcode');
      const ck=(document.cookie.match(/(?:^|;\\s*)vcode=([^;]*)/)||[])[1]||'';
      return {
        popShown: !!(pop && getComputedStyle(pop).display!=='none'),
        src: img ? (img.src||'') : '',
        natural: img ? (img.naturalWidth+'x'+img.naturalHeight) : '',
        tipText: tip ? (tip.innerText||'').trim() : '',
        tipShown: !!(tip && getComputedStyle(tip).display!=='none' && (tip.innerText||'').trim()),
        inputVal: inp ? (inp.value||'') : '',
        cookie: ck,
      };
    }""")


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    api_key = load_captcha_key()
    solver = YesCaptcha(api_key, "cn", print)
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
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
        time.sleep(4)

        st = state(page)
        print("弹层:", st["popShown"], "| natural:", st["natural"])
        print("img src:", st["src"])

        # ---- 用 APIRequestContext 取字节 ----
        for attempt in range(1, 4):
            src = state(page)["src"]
            print("\n第 %d 轮，取图：%s" % (attempt, src[:90]))
            resp = page.request.get(src, headers={"Referer": "https://www.creditchina.gov.cn/",
                                                  "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
            body = resp.body()
            print("  status=%s ct=%s len=%d head=%r"
                  % (resp.status, resp.headers.get("content-type"), len(body), body[:12]))
            fn = os.path.join(OUT, "cc_api_%d.png" % attempt)
            open(fn, "wb").write(body)
            text = solver.solve_image_to_text(body)
            print("  识别 = %r -> %s" % (text, fn))
            if not text:
                break
            page.evaluate("""(t)=>{const e=document.getElementById('vcode'); e.focus();
                const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                s.call(e,t); e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));}""", text)
            time.sleep(0.4)
            page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm')"
                          "||document.querySelector('.vcodepop .confirm'); if(b) b.click();}")
            time.sleep(3.5)
            st2 = state(page)
            print("  提交后: tip=%r shown=%s cookie=%r popShown=%s"
                  % (st2["tipText"], st2["tipShown"], st2["cookie"], st2["popShown"]))
            if st2["cookie"] == "1" or not st2["popShown"]:
                print("  ==> 通过！")
                break
            print("  ==> 验证码错误，点「换一张」再试")
            page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                          " if(s) s.click();}")
            time.sleep(2.5)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
