# -*- coding: utf-8 -*-
"""CNCA 导航链与查询前置验证（不涉及极验）。

验三件事：
  1. 从上级目录（国家认监委官网）能否跳进 cx.cnca.cn；
  2. 首页企业名称输入框填入是否生效、点【查询】是否弹出极验；
  3. 极验弹层的 DOM 与 CSS 类名（供 wait_geetest 精确识别）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav
from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)
COMPANY = "中瑞盛世（北京）建筑有限公司"


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()

        print("=== 1) 走上级目录跳转 ===")
        res = nav.goto_via_landing(page, "cnca", log=print, timeout_ms=60000)
        print("跳转结果:", {k: v for k, v in res.items() if k != "state"})
        page = res.get("page") or page
        print("当前 URL:", page.url)
        print("当前 title:", page.title())

        if "cx.cnca.cn" not in (page.url or ""):
            print("⚠ 未跳到目标站，改用直达")
            nav.goto(page, "https://cx.cnca.cn/CertECloud/index/index/page",
                     timeout_ms=60000, log=print)
            time.sleep(4)

        print("\n=== 2) 首页输入框 ===")
        info = page.evaluate("""()=>{
          const e=document.getElementById('orgName');
          return {exists:!!e, ph:e?e.placeholder:'', visible:e?
            (e.getBoundingClientRect().width>0):false};
        }""")
        print("orgName:", json.dumps(info, ensure_ascii=False))

        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(!e) return;
          e.focus();
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')
            .set.call(e,name);
          e.dispatchEvent(new Event('input',{bubbles:true}));
          e.dispatchEvent(new Event('change',{bubbles:true}));
        }""", COMPANY)
        time.sleep(0.8)
        val = page.evaluate("()=>document.getElementById('orgName').value")
        print("填入后的值:", repr(val), "匹配" if val == COMPANY else "不匹配")

        print("\n=== 3) 点查询，检测极验 ===")
        page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(b) b.click();
        }""")
        time.sleep(6)
        gt = page.evaluate("""()=>{
          const els=[...document.querySelectorAll(
            '[class*=geetest_box],[class*=geetest_popup],[class*=geetest_panel]')];
          const vis=els.filter(e=>{const b=e.getBoundingClientRect();
            return b.width>20&&b.height>20;});
          return {count:els.length, visible:vis.length,
                  classes:vis.map(e=>e.className).slice(0,5),
                  text:vis.map(e=>(e.innerText||'').replace(/\\s+/g,' ').slice(0,80)),
                  url:location.href};
        }""")
        print("极验状态:", json.dumps(gt, ensure_ascii=False, indent=1))
        page.screenshot(path=os.path.join(OUT, "f01_query.png"))
        print("截图：probe_out/cnca/f01_query.png")

        print("\n=== 4) 验证 wait_geetest 的可见性判定 ===")
        vis = page.evaluate("""()=>{
          const els=[...document.querySelectorAll(
            '[class*=geetest_box],[class*=geetest_popup],[class*=geetest_panel]')];
          return els.some(e=>{
            const b=e.getBoundingClientRect();
            return b.width>20 && b.height>20;
          });
        }""")
        print("geetest_visible 判定:", vis)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
