# -*- coding: utf-8 -*-
"""检查 gsxt 登录框与极验验证的流程逻辑。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

JS_INSPECT = """
()=>{
  const out = {};
  const btn = document.getElementById('btn_login');
  out.hasBtn = !!btn;
  if(btn){
    out.btnOnclick = String(btn.onclick);
  }
  // 查找全局定义的 login 函数
  out.windowLogin = typeof window.login;
  out.windowUserLogin = typeof window.userLogin;
  // 查找包含 btn_login 或 geetest 的脚本片段
  const scripts = [...document.querySelectorAll('script')]
    .map(s => s.innerText || s.textContent || '')
    .filter(t => t.includes('btn_login') || t.includes('geetest') || t.includes('loginBox'))
    .map(t => t.slice(0, 2000));
  out.scripts = scripts;
  return out;
}
"""

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "gsxt", log=print, timeout_ms=45000)
        p = res.get("page") or page
        time.sleep(3)
        # 点击登录，展开登录框
        p.evaluate("""()=>{
          const els=[...document.querySelectorAll('a,span,button')];
          const hit=els.find(e=>(e.innerText||'').trim()==='登录');
          if(hit) hit.click();
        }""")
        time.sleep(2)
        info = p.evaluate(JS_INSPECT)
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2)[:4000])
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
