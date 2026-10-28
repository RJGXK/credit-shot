# -*- coding: utf-8 -*-
"""自动化探测 CNCA 前端 JS 函数和直接进入结果页/组织列表的 URL 路由与接口。"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"

JS_FUNCS = """
()=>{
  const out = {};
  out.indexQueryCert = String(window.indexQueryCert || '');
  out.skipPage = String(window.skipPage || '');
  out.queryCert = String(window.queryCert || '');
  out.queryOrg = String(window.queryOrg || '');

  // 找页面中所有 onclick 包含 query / cert / org 的按钮或链接
  out.actions = [...document.querySelectorAll('[onclick]')].map(e=>({
    tag: e.tagName,
    text: (e.innerText||'').trim().slice(0, 30),
    onclick: e.getAttribute('onclick')
  })).filter(x=>/cert|org|query|skip/i.test(x.onclick));

  return out;
}
"""

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(TARGET, wait_until="networkidle", timeout=45000)
        time.sleep(2)
        info = page.evaluate(JS_FUNCS)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
