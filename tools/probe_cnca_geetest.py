# -*- coding: utf-8 -*-
"""诊断 CNCA 极验弹层：对比「点查询前 / 点查询后」的 DOM 状态。

目的：确定一个**可靠**的「弹层已展开」判据
（不能只看 .geetest_box —— 它一直存在且带固定高度）。
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
  const info={url:location.href, path:location.pathname};
  const orgName=document.getElementById('orgName');
  info.orgNameVal=orgName?orgName.value:'(缺)';
  info.orgNameIdx=(document.getElementById('orgNameIndex')||{}).value;
  info.fromIndex=(document.getElementById('fromIndex')||{}).value;
  info.zonghe=(document.getElementById('zonghe')||{}).value;
  info.certItem=(document.getElementById('certItem')||{}).value;
  info.gtExists=!!window.gt;
  info.showCaptchaCalls=window.__gtCalls||0;
  info.gtState=window.gt&&window.gt.getType?String(window.gt.getType()):'';
  const els=[...document.querySelectorAll('[class*=geetest]')];
  info.geetest=els.slice(0,10).map(e=>{
    const r=e.getBoundingClientRect();
    const chain=[];
    let n=e;
    while(n&&n!==document.documentElement){
      const st=getComputedStyle(n);
      chain.push((n.tagName||'')+'#'+(n.id||'')+'.'+(String(n.className||'').split(/\\s+/)[0]||'')
        +'[d='+st.display+',h='+n.offsetHeight+',w='+n.offsetWidth+']');
      n=n.parentElement;
    }
    return {cls:String(e.className||'').slice(0,70), tag:e.tagName,
            off:[e.offsetWidth,e.offsetHeight],
            rect:[Math.round(r.width),Math.round(r.height)],
            chain:chain.slice(0,6)};
  });
  info.vis=(info.geetest||[]).filter(g=>g.rect[0]>30&&g.rect[1]>30).length;
  return info;
}"""


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)

        # 记录 gt.showCaptcha 的调用次数
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

        print("===== 点查询前 =====")
        print(json.dumps(page.evaluate(DUMP), ensure_ascii=False, indent=1)[:3500])

        # 填企业名 + 点查询
        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          e.focus();
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')
            .set.call(e,name);
          e.dispatchEvent(new Event('input',{bubbles:true}));
          e.dispatchEvent(new Event('change',{bubbles:true}));
        }""", COMPANY)
        time.sleep(0.6)
        page.evaluate("""()=>{
          const b=[...document.querySelectorAll('button')]
            .find(x=>/queryCertInfo/.test(x.getAttribute('onclick')||''));
          if(b) b.click();
        }""")

        for i in range(1, 13):
            time.sleep(2)
            d = page.evaluate(DUMP)
            print("\n----- t=%ds  showCaptchaCalls=%s vis=%s url=%s"
                  % (i * 2, d.get("showCaptchaCalls"), d.get("vis"),
                     str(d.get("url"))[-60:]))
            print("   orgName=%r  fromIndex=%r  zonghe=%r certItem=%r gt=%s"
                  % (d.get("orgNameVal"), d.get("fromIndex"), d.get("zonghe"),
                     d.get("certItem"), d.get("gtExists")))
            for g in (d.get("geetest") or [])[:5]:
                print("   %-70s off=%s rect=%s" % (g["cls"][:70], g["off"], g["rect"]))
            if i == 2:
                page.screenshot(path=os.path.join(OUT, "gt_after.png"))
            if d.get("showCaptchaCalls"):
                break
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
