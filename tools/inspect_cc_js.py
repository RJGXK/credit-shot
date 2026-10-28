# -*- coding: utf-8 -*-
"""检查信用中国前端页面对验证码的控制逻辑：
看它是怎么加载验证码、何时刷新、是否有定时器、点击验证后做什么。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"

JS_INSPECT = """
()=>{
  // 查找绑定在 #vcodeimg、.vcodepop、.confirm、span 上的事件或函数
  const out = {};
  const img = document.getElementById('vcodeimg');
  out.imgSrc = img ? img.src : '';
  out.imgOnclick = img ? String(img.onclick) : '';
  const span = document.querySelector('.vcodepop .vcodeimgbox span');
  out.spanOnclick = span ? String(span.onclick) : '';
  const confirm = document.querySelector('.vcodepop a.confirm');
  out.confirmOnclick = confirm ? String(confirm.onclick) : '';

  // 检查全局变量/函数中是否有 getVerify / vcode 相关
  const funcs = [];
  for(const k of Object.keys(window)){
    if(/vcode|verify|code|captcha/i.test(k)){
      funcs.push(k + ': ' + typeof window[k]);
    }
  }
  out.windowKeys = funcs;

  // 抓取包含 getVerify 的全部 script 内容片段
  const scripts = [...document.querySelectorAll('script')]
    .map(s => s.innerText || s.textContent || '')
    .filter(t => t.includes('getVerify') || t.includes('checkVerify') || t.includes('vcodepop'))
    .map(t => t.slice(0, 1500));
  out.scripts = scripts;
  return out;
}
"""

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        p = res.get("page") or page
        nav.goto(p, TARGET, timeout_ms=45000, log=print)
        time.sleep(3)
        info = p.evaluate(JS_INSPECT)
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2)[:4000])
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
