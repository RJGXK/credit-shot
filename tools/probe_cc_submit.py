# -*- coding: utf-8 -*-
"""探针：信用中国验证码「等图加载 -> 识别 -> 填入 -> 提交 -> 判错 -> 换图」全链路实测。

要验证：
1. #vcodeimg 首次是否加载成功（naturalWidth>0），没加载成功时点「看不清? 换一张」是否只换图；
2. 真服务识别结果填入 #vcode 后点 a.confirm，站点是否通过（cookie vcode=1）；
3. 识别错误时 .errortip 是否显示「验证码错误」，站点是否自动换图。
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
        complete: img ? !!img.complete : false,
        tipText: tip ? (tip.innerText||'').trim() : '',
        tipShown: !!(tip && getComputedStyle(tip).display!=='none' && (tip.innerText||'').trim()),
        inputVal: inp ? (inp.value||'') : '',
        cookie: ck,
        docStart: performance.timeOrigin,
      };
    }""")


def wait_img_ready(page, timeout=12):
    """等 #vcodeimg 真正加载完（complete && naturalWidth>0）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = state(page)
        if st["natural"] and st["natural"] != "0x0" and st["complete"]:
            return True
        time.sleep(0.5)
    return False


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    api_key = load_captcha_key()
    print("API Key:", (api_key[:6] + "...") if api_key else "(空)")
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
        handle = page.evaluate_handle(finder)
        el = handle.as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")

        deadline = time.time() + 25
        while time.time() < deadline:
            if state(page)["popShown"]:
                break
            time.sleep(1.0)
        st = state(page)
        print("弹层已显示:", st["popShown"], "| 图 natural=", st["natural"],
              "| complete=", st["complete"])

        ready = wait_img_ready(page, 12)
        print("图片加载完成:", ready, "| natural=", state(page)["natural"])
        if not ready:
            before = state(page)["docStart"]
            page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                          " if(s) s.click();}")
            time.sleep(2.5)
            st3 = state(page)
            print("点「换一张」后 natural=%s 页面刷新=%s"
                  % (st3["natural"], st3["docStart"] != before))
            wait_img_ready(page, 12)

        for attempt in range(1, 4):
            img = page.query_selector("#vcodeimg")
            raw = img.screenshot(timeout=20000)
            shot = os.path.join(OUT, "cc_vcode_%d.png" % attempt)
            open(shot, "wb").write(raw)
            text = solver.solve_captcha_image_element(img)
            print("第 %d 次识别 = %r" % (attempt, text))
            if not text:
                break
            page.evaluate("""(t)=>{const e=document.getElementById('vcode'); e.focus();
                const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                s.call(e,t); e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));}""", text)
            time.sleep(0.4)
            print("  填入后 input =", repr(state(page)["inputVal"]))
            page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm')"
                          "||document.querySelector('.vcodepop .confirm'); if(b) b.click();}")
            time.sleep(3.0)
            st2 = state(page)
            print("  提交后: tip=%r shown=%s cookie=%r popShown=%s src=%s"
                  % (st2["tipText"], st2["tipShown"], st2["cookie"],
                     st2["popShown"], st2["src"][-28:]))
            if st2["cookie"] == "1" or not st2["popShown"]:
                print("  ==> 通过")
                break
            print("  ==> 验证码错误；观察站点是否自动换图 …")
            time.sleep(2.0)
            st3 = state(page)
            print("     2 秒后 src=%s (换图了=%s)"
                  % (st3["src"][-28:], st3["src"] != st2["src"]))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
