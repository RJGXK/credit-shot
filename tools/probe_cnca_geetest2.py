# -*- coding: utf-8 -*-
"""诊断 CNCA 极验：找「弹层已展开」的可靠信号。

要点：展开与收起时 .geetest_captcha / .geetest_box_wrap 的 offsetHeight
**都是 0**（极验 v4 用绝对定位+溢出显示），尺寸判据完全失效。
本脚本对比「点查询前 / 点查询后」的 iframe 与 class 差异。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)
COMPANY = "中瑞盛世（北京）建筑有限公司"

URL = ("https://cx.cnca.cn/CertECloud/result/skipResultList"
       "?certNumber=&orgName=%E4%B8%AD%E7%91%9E%E7%9B%9B%E4%B8%96"
       "%EF%BC%88%E5%8C%97%E4%BA%AC%EF%BC%89%E5%BB%BA%E7%AD%91%E6%9C%89"
       "%E9%99%90%E5%85%AC%E5%8F%B8&fromIndex=true")

DUMP = """()=>{
  const r={};
  r.frames=[...document.querySelectorAll('iframe')].map(f=>{
    const b=f.getBoundingClientRect();
    return {src:(f.src||'').slice(0,90), cls:String(f.className||''),
            off:[f.offsetWidth,f.offsetHeight],
            rect:[Math.round(b.width),Math.round(b.height),
                  Math.round(b.top),Math.round(b.left)]};});
  r.gtCap=(document.querySelector('.geetest_captcha')||{}).className||'';
  r.gtWrap=(document.querySelector('.geetest_box_wrap')||{}).className||'';
  r.gtPanel=(document.querySelector('.geetest_panel')||{}).className||'';
  r.gtBox=(document.querySelector('.geetest_box')||{}).className||'';
  const box=document.querySelector('.geetest_box');
  if(box){const b=box.getBoundingClientRect();
    r.boxRect=[Math.round(b.width),Math.round(b.height),
               Math.round(b.top),Math.round(b.left)];}
  r.calls=window.__gtCalls||0;
  r.html=((document.querySelector('.geetest_captcha')||{}).innerHTML||'').length;
  r.widget=document.querySelectorAll('[class*=widget]').length;
  r.panelCount=document.querySelectorAll('.geetest_panel').length;
  return r;
}"""


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        page.evaluate("""()=>{
          window.__gtCalls=0;
          const iv=setInterval(()=>{
            if(window.gt&&window.gt.showCaptcha&&!window.gt.__hooked){
              const o=window.gt.showCaptcha.bind(window.gt);
              window.gt.showCaptcha=function(){window.__gtCalls++;return o.apply(window.gt,arguments);};
              window.gt.__hooked=true;
            }
          },100);
        }""")

        print("===== 前（未点查询）=====")
        print(json.dumps(page.evaluate(DUMP), ensure_ascii=False, indent=1)[:2600])

        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          e.focus();
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')
            .set.call(e,name);
          e.dispatchEvent(new Event('input',{bubbles:true}));
          e.dispatchEvent(new Event('change',{bubbles:true}));
        }""", COMPANY)
        time.sleep(0.5)
        page.evaluate("""()=>{
          const b=[...document.querySelectorAll('button')]
            .find(x=>/queryCertInfo/.test(x.getAttribute('onclick')||''));
          if(b) b.click();
        }""")

        for i in range(1, 16):
            time.sleep(2)
            d = page.evaluate(DUMP)
            print("\n----- t=%ds calls=%s" % (i * 2, d.get("calls")))
            print("   boxRect=%s panelCount=%s widget=%s innerLen=%s"
                  % (d.get("boxRect"), d.get("panelCount"), d.get("widget"),
                     d.get("html")))
            print("   cap=%s" % str(d.get("gtCap"))[:130])
            print("   wrap=%s" % str(d.get("gtWrap"))[:130])
            print("   box=%s" % str(d.get("gtBox"))[:130])
            for f in (d.get("frames") or []):
                print("   FRAME %s" % json.dumps(f, ensure_ascii=False)[:200])
            if i == 3:
                page.screenshot(path=os.path.join(OUT, "gt_open.png"))
            if i > 6 and d.get("calls"):
                break
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
