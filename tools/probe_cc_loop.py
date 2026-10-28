# -*- coding: utf-8 -*-
"""探针（决定性）：信用中国验证码完整闭环。

流程：弹层 -> 取图（img 已加载就用 img，否则用 API 取字节并回填 data URL 让用户看得见）
     -> 识别 -> 填入 -> 点 a.confirm -> 判错 -> 点「换一张」-> 重新取图识别 -> 再提交。
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


def get_image(page):
    """取验证码图片字节。返回 (bytes, 说明)。"""
    st = state(page)
    nat = st["natural"]
    if nat and nat != "0x0":
        img = page.query_selector("#vcodeimg")
        return img.screenshot(timeout=20000), "img截图(%s)" % nat
    src = st["src"]
    resp = page.request.get(src, headers={"Accept": "image/*,*/*;q=0.8",
                                           "Referer": "https://www.creditchina.gov.cn/"})
    body = resp.body()
    ct = resp.headers.get("content-type", "")
    if resp.status == 200 and ("image" in ct or body[:2] in (b"\xff\xd8", b"\x89P")):
        # 回填到 <img>，让用户也能看见这张验证码（data URL 不会触发新请求）
        import base64
        b64 = base64.b64encode(body).decode("ascii")
        page.evaluate("""(d)=>{const i=document.getElementById('vcodeimg');
            if(i){ i.src='data:image/png;base64,'+d; i.style.width='130px';
                   i.style.height='46px'; }}""", b64)
        return body, "API取图(%s, %d字节)" % (ct, len(body))
    return None, "取图失败 status=%s ct=%s len=%d" % (resp.status, ct, len(body))


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

        for attempt in range(1, 5):
            st = state(page)
            if not st["popShown"]:
                print("弹层已关闭，结束（第 %d 轮）" % attempt)
                break
            raw, how = get_image(page)
            print("\n第 %d 轮：%s" % (attempt, how))
            if not raw:
                print("  取不到图，放弃")
                break
            fn = os.path.join(OUT, "cc_loop_%d.png" % attempt)
            open(fn, "wb").write(raw)
            try:
                text = solver.solve_image_to_text(raw)
            except Exception as exc:
                print("  识别异常:", exc)
                text = ""
            print("  识别 = %r" % text)
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
            print("  ==> 验证码错误，点「看不清? 换一张」")
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
