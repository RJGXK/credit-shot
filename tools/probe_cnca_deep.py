# -*- coding: utf-8 -*-
"""CNCA 深度探针：抓全部请求（含 JS 资源）、结果页 DOM、证书列表与详情入口。

关键问题：
  1. 极验点选弹层能否关闭后继续？关闭后列表是否照常加载？
  2. 结果页里「组织列表 / 获证组织」的 DOM 到底是什么？
  3. 展开证书列表、查看详细信息的元素 id/class；
  4. 各阶段图形验证码的输入框 id（#checkCodeOrg / #checkCodeForListByOrg / #checkCode1）。
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)

SCRIPTS = []
XHR = []


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()

        def on_req(req):
            rt = req.resource_type
            if rt == "script":
                SCRIPTS.append(req.url)
            elif rt in ("xhr", "fetch"):
                XHR.append({"m": req.method, "u": req.url,
                            "post": (req.post_data or "")[:300]})

        page.on("request", on_req)

        page.goto(TARGET, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        company = "中瑞盛世（北京）建筑有限公司"
        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(e){ e.focus(); e.value=name;
            e.dispatchEvent(new Event('input',{bubbles:true}));
            e.dispatchEvent(new Event('change',{bubbles:true})); }
        }""", company)
        time.sleep(1)
        page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(b) b.click();
        }""")
        time.sleep(6)
        print("URL after query:", page.url)

        # 尝试关闭极验弹层，看列表是否照常加载
        print("\n>>> 尝试关闭极验弹层")
        closed = page.evaluate("""()=>{
          const b=document.querySelector('.geetest_close, [class*=geetest_close]');
          if(!b) return 'NO_BTN';
          b.click(); return 'CLICKED';
        }""")
        print("关闭结果:", closed)
        time.sleep(4)

        # 抓结果页 DOM
        info = page.evaluate("""()=>{
          const vis = e => { const b=e.getBoundingClientRect(); return b.width>0&&b.height>0; };
          const out = {};
          out.url = location.href;
          out.geetestVisible = [...document.querySelectorAll('[class*=geetest_box],[class*=geetest_popup]')]
            .some(e=>vis(e));
          out.inputs = [...document.querySelectorAll('input')].filter(vis)
            .map(e=>({id:e.id,name:e.name,cls:(e.className||'').toString().slice(0,40),
                      ph:e.placeholder, type:e.type}));
          out.tables = [...document.querySelectorAll('table')].map(t=>({
            cls:(t.className||'').toString().slice(0,50),
            headers:[...t.querySelectorAll('th')].map(x=>x.innerText.trim()),
            rows:t.querySelectorAll('tbody tr').length,
            first:[...(t.querySelectorAll('tbody tr')[0]?.querySelectorAll('td')||[])]
                 .map(x=>x.innerText.replace(/\\s+/g,' ').trim().slice(0,30))
          }));
          out.links = [...document.querySelectorAll('a')].filter(vis)
            .map(e=>({t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30),
                       href:(e.getAttribute('href')||'').slice(0,80),
                       onclick:(e.getAttribute('onclick')||'').slice(0,80)}))
            .filter(x=>x.t).slice(0,60);
          out.btns = [...document.querySelectorAll('button')].filter(vis)
            .map(e=>({t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,20),
                      cls:(e.className||'').toString().slice(0,40),
                      onclick:(e.getAttribute('onclick')||'').slice(0,80)}));
          out.body = (document.body?document.body.innerText:'').replace(/\\n+/g,' | ').slice(0,1200);
          return out;
        }""")
        print("\n===== 结果页 DOM =====")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:6000])
        page.screenshot(path=os.path.join(OUT, "d01_result.png"), full_page=True)

        print("\n===== 脚本资源 =====")
        for s in SCRIPTS:
            print(" ", s)

        with open(os.path.join(OUT, "d_xhr.json"), "w", encoding="utf-8") as f:
            json.dump(XHR, f, ensure_ascii=False, indent=2)
        with open(os.path.join(OUT, "d_scripts.json"), "w", encoding="utf-8") as f:
            json.dump(SCRIPTS, f, ensure_ascii=False, indent=2)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
