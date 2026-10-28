# -*- coding: utf-8 -*-
"""CNCA 结果页容器显隐探查：确认 .orgContent / .certContent 的父链与可见性。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

URL = ("https://cx.cnca.cn/CertECloud/result/skipResultList"
       "?certNumber=&orgName=%E4%B8%AD%E7%91%9E%E7%9B%9B%E4%B8%96"
       "%EF%BC%88%E5%8C%97%E4%BA%AC%EF%BC%89%E5%BB%BA%E7%AD%91%E6%9C%89"
       "%E9%99%90%E5%85%AC%E5%8F%B8&fromIndex=true")


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        info = page.evaluate("""()=>{
          const chain=(sel)=>{
            const e=document.querySelector(sel);
            if(!e) return null;
            const out=[];
            let n=e;
            while(n && n!==document.documentElement){
              const st=getComputedStyle(n);
              out.push({tag:n.tagName, id:n.id||'', cls:n.className||'',
                        disp:st.display, vis:st.visibility, h:n.offsetHeight});
              n=n.parentElement;
            }
            return out;
          };
          return {
            orgContent:chain('.orgContent'),
            certContent:chain('.certContent'),
            orgListDiv:chain('#orgListDiv'),
            captcha:chain('#captcha'),
            geetestEls:[...document.querySelectorAll('[class*=geetest]')]
              .map(e=>({cls:e.className, tag:e.tagName, h:e.offsetHeight,
                        vis:getComputedStyle(e).visibility})).slice(0,12),
            hiddenFields:['orgNameIndex','certNumberIndex','fromIndex','isSelf','certItem']
              .map(id=>{const e=document.getElementById(id);
                        return id+'='+(e?e.value:'(缺)')}),
          };
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:5000])
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
