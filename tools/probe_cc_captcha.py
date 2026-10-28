# -*- coding: utf-8 -*-
"""探针：看清「信用中国」验证码弹层(.vcodepop)的真实结构。

目的
----
1. 找到**只刷新验证码图片**的控件（不能刷新整个页面）；
2. 找到提交后「验证码错误」提示出现的位置/文案；
3. 确认验证码输入框与「验证」按钮的选择器。

用法：python tools/probe_cc_captcha.py [公司名]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

DUMP_JS = """
()=>{
  const pop=document.querySelector('.vcodepop');
  const res={popFound:!!pop};
  if(pop){
    res.popHtml=(pop.outerHTML||'').slice(0,4000);
    res.popText=(pop.innerText||'').replace(/\\s+/g,' ').slice(0,600);
    const r=pop.getBoundingClientRect();
    res.popRect={x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
    res.popVisible=getComputedStyle(pop).display!=='none';
    // 弹层里所有可点元素
    res.popClicks=[...pop.querySelectorAll('a,button,span,div,img,i,label,em,input')]
      .map(e=>({
        tag:e.tagName, id:e.id||'', cls:(e.className||'').toString().slice(0,40),
        txt:(e.innerText||e.value||e.getAttribute('alt')||e.title||'').replace(/\\s+/g,' ').slice(0,30),
        onclick:(e.getAttribute('onclick')||'').slice(0,80),
        src:(e.getAttribute('src')||'').slice(0,80),
        href:(e.getAttribute('href')||'').slice(0,60),
      }));
  }
  // 全页面里与「刷新/换一张/看不清」相关的元素
  res.pageRefresh=[...document.querySelectorAll('a,button,span,div,i,em,img')]
    .filter(e=>/换一|刷新|看不清|重新|换张/i.test(
        (e.innerText||'')+' '+(e.title||'')+' '+(e.className||'')+' '+(e.id||'')))
    .map(e=>({tag:e.tagName,id:e.id||'',cls:(e.className||'').toString().slice(0,40),
              txt:(e.innerText||'').replace(/\\s+/g,' ').slice(0,30),
              src:(e.getAttribute('src')||'').slice(0,70)}));
  const img=document.querySelector('#vcodeimg');
  if(img){ const b=img.getBoundingClientRect();
    res.img={src:(img.src||'').slice(0,140), nw:img.naturalWidth, nh:img.naturalHeight,
             w:Math.round(b.width),h:Math.round(b.height),
             cls:(img.className||''), id:img.id,
             onclick:(img.getAttribute('onclick')||'').slice(0,100)}; }
  // 输入框
  res.inputs=[...document.querySelectorAll('input:not([type=hidden]),textarea')].map(e=>({
      id:e.id||'',name:e.name||'',cls:(e.className||'').toString().slice(0,30),
      ph:e.placeholder||'', type:e.type||'', vis:!!e.offsetParent}));
  // 错误提示容器
  res.errs=[...document.querySelectorAll('div,span,p,label')]
    .filter(e=>/验证码错误|验证码不正确|错误|不正确/.test(e.innerText||''))
    .map(e=>({tag:e.tagName,id:e.id||'',cls:(e.className||'').toString().slice(0,40),
              txt:(e.innerText||'').replace(/\\s+/g,' ').slice(0,80),
              vis:!!e.offsetParent}));
  return res;
}
"""


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
        print("浏览器就绪")
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        print("落地:", res.get("ok"), res.get("reason", ""))
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        page.evaluate(finder + " && (()=>{})()")
        handle = page.evaluate_handle(finder)
        el = handle.as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")
        print("已点查询，等验证码弹层…")

        shown = False
        deadline = time.time() + 25
        while time.time() < deadline:
            st = page.evaluate("""()=>{const p=document.querySelector('.vcodepop');
                return {shown: !!(p && getComputedStyle(p).display!=='none'),
                        imgOk: (()=>{const i=document.querySelector('#vcodeimg');
                             return !!(i&&i.naturalWidth>0);})()};}""")
            if st.get("shown"):
                shown = True
                break
            time.sleep(1.0)
        print("验证码弹层:", shown)
        time.sleep(2)

        info = page.evaluate(DUMP_JS)
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2)[:12000])

        shot = os.path.join(OUT, "cc_captcha_pop.png")
        try:
            page.screenshot(path=shot, full_page=False)
            print("截图:", shot)
        except Exception as exc:
            print("截图失败:", exc)

        # 只看弹层里的元素
        if info.get("popFound"):
            try:
                pop = page.query_selector(".vcodepop")
                pshot = os.path.join(OUT, "cc_captcha_only.png")
                pop.screenshot(path=pshot, timeout=15000)
                print("弹层截图:", pshot)
            except Exception as exc:
                print("弹层截图失败:", exc)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
