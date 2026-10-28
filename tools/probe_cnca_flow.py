# -*- coding: utf-8 -*-
"""CNCA 全链路探针：抓网络请求 + DOM 结构 + 弹层。

目的：搞清楚
  1. 点「查询」后到底调了哪些接口（XHR），参数是什么；
  2. 极验弹层长什么样、能不能自动过；
  3. 过验证码后进入的「认证结果综合查询」页面结构；
  4. 「组织列表」入口、证书列表、查看详细信息的元素。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)

REQS = []


def dump_page(page, tag):
    info = page.evaluate("""()=>{
      const vis = e => { const b=e.getBoundingClientRect();
        return b.width>0 && b.height>0; };
      const pick = (sel) => [...document.querySelectorAll(sel)]
        .filter(vis)
        .map(e=>({tag:e.tagName, id:e.id, cls:(e.className||'').toString().slice(0,60),
                  text:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40)}));
      return {
        url: location.href,
        title: document.title,
        inputs: pick('input'),
        buttons: pick('button,a.btn,[onclick]'),
        geetest: pick('[class*=geetest]'),
        modal: pick('.modal,.layui-layer,.van-dialog,.el-dialog,[class*=popup],[class*=dialog]'),
        bodyText: (document.body?document.body.innerText:'').replace(/\\n+/g,' | ').slice(0,1500)
      };
    }""")
    print("\n===== %s =====" % tag)
    print("URL:", info["url"], "| TITLE:", info["title"])
    for k in ("inputs", "buttons", "geetest", "modal"):
        if info[k]:
            print("  %s: %s" % (k, json.dumps(info[k], ensure_ascii=False)[:1200]))
    print("  BODY:", info["bodyText"][:900])
    return info


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()

        def on_req(req):
            if req.resource_type in ("xhr", "fetch"):
                REQS.append({"m": req.method, "u": req.url,
                             "post": (req.post_data or "")[:400]})

        page.on("request", on_req)

        page.goto(TARGET, wait_until="networkidle", timeout=60000)
        time.sleep(3)
        dump_page(page, "01 首页")

        company = "中瑞盛世（北京）建筑有限公司"
        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(e){ e.focus(); e.value=name;
            e.dispatchEvent(new Event('input',{bubbles:true}));
            e.dispatchEvent(new Event('change',{bubbles:true})); }
        }""", company)
        time.sleep(1)

        print("\n>>> 点击「查询」")
        page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(b){ b.click(); return 'CLICKED'; }
          return 'NONE';
        }""")
        time.sleep(6)
        dump_page(page, "02 点查询后")
        page.screenshot(path=os.path.join(OUT, "p02_after_query.png"))

        # 极验弹层特写
        gt = page.evaluate("""()=>{
          const g=document.querySelector('.geetest_holder, [class*=geetest]');
          if(!g) return null;
          const b=g.getBoundingClientRect();
          return {cls:g.className, w:b.width, h:b.height,
                  text:(g.innerText||'').replace(/\\s+/g,' ').slice(0,200),
                  canvases:g.querySelectorAll('canvas').length,
                  imgs:[...g.querySelectorAll('img')].map(i=>i.src.slice(0,120))};
        }""")
        print("\nGEETEST:", json.dumps(gt, ensure_ascii=False))

        print("\n>>> XHR 请求：")
        for r in REQS:
            print("  %s %s" % (r["m"], r["u"]))
            if r["post"]:
                print("      POST: %s" % r["post"])

        with open(os.path.join(OUT, "p_requests.json"), "w", encoding="utf-8") as f:
            json.dump(REQS, f, ensure_ascii=False, indent=2)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
