# -*- coding: utf-8 -*-
"""探测 CNCA 首页点击查询后的弹层与验证码结构。"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"

DUMP_POP = """
()=>{
  const out = {};
  out.imgs = [...document.querySelectorAll('img')].map(i=>({
    id: i.id, src: i.src.slice(0, 80), w: i.offsetWidth, h: i.offsetHeight,
    onclick: String(i.onclick)
  }));
  // 查找弹窗或 dialog
  const modals = [...document.querySelectorAll('.modal, .dialog, [class*=modal], [class*=dialog], [class*=pop], [class*=layui]')].filter(m=>m.offsetWidth>0);
  out.modals = modals.map(m=>({
    cls: m.className, id: m.id,
    txt: (m.innerText||'').replace(/\\s+/g, ' ').slice(0, 150)
  }));
  return out;
}
"""

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(TARGET, wait_until="networkidle", timeout=45000)
        time.sleep(3)
        # 填入企业名称
        page.evaluate("()=>{const e=document.getElementById('orgName'); if(e){ e.focus(); e.value='中瑞盛世（北京）建筑有限公司'; e.dispatchEvent(new Event('input',{bubbles:true})); }}")
        time.sleep(1)
        # 点击查询按钮
        print("点击【查 询】按钮…")
        page.evaluate("()=>{const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询'); if(b) b.click();}")
        time.sleep(3)

        info = page.evaluate(DUMP_POP)
        print("查询后页面元素：", json.dumps(info, ensure_ascii=False, indent=2))
        page.screenshot(path="probe_out/cnca/02_after_query.png")
        print("截图：probe_out/cnca/02_after_query.png")
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
