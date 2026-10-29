# -*- coding: utf-8 -*-
"""探针：看清 gsxt 登录页（shiming.gsxt.gov.cn）的真实结构。

重点：
1. 登录表单里有没有**图形验证码图片**（有的话打码服务能自动过）；
2. 提交后弹的是**极验 geetest**（只能人工）还是别的；
3. 人工过码后页面靠什么标志表示成功。

不填真实账号密码、不提交。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

LOGIN_URL = "https://shiming.gsxt.gov.cn/socialuser-use-rllogin.html"

DUMP = """
()=>{
  const out={url:location.href, title:document.title};
  out.inputs=[...document.querySelectorAll('input')].map(e=>({
      id:e.id||'', name:e.name||'', type:e.type||'',
      ph:e.placeholder||'', cls:(e.className||'').toString().slice(0,40),
      vis:!!e.offsetParent}));
  out.imgs=[...document.querySelectorAll('img')].map(e=>({
      id:e.id||'', cls:(e.className||'').toString().slice(0,40),
      src:(e.src||'').slice(0,110), nat:e.naturalWidth+'x'+e.naturalHeight,
      vis:!!e.offsetParent}));
  out.buttons=[...document.querySelectorAll('button,a,div[id*=btn],input[type=submit]')]
      .map(e=>({tag:e.tagName, id:e.id||'',
                cls:(e.className||'').toString().slice(0,40),
                txt:(e.innerText||e.value||'').replace(/\\s+/g,'').slice(0,20)}))
      .filter(o=>o.txt||o.id);
  out.geetest=[...document.querySelectorAll('[class*=geetest],[id*=geetest]')]
      .map(e=>{const b=e.getBoundingClientRect(); const st=getComputedStyle(e);
        return {cls:(e.className||'').toString().slice(0,50), id:e.id||'',
                w:Math.round(b.width), h:Math.round(b.height),
                disp:st.display, vis:st.visibility, op:st.opacity,
                shown:!!e.offsetParent};});
  out.text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,700);
  out.cookies=document.cookie;
  return out;
}
"""


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print("直达登录页失败:", str(exc)[:100])
            return
        time.sleep(4)
        info = page.evaluate(DUMP)
        print(json.dumps(info, ensure_ascii=False, indent=2)[:5000])

        # 提交一次（用假密码），看弹的是什么验证
        try:
            page.evaluate("""()=>{
              const set=(id,v)=>{const e=document.getElementById(id); if(!e) return;
                const s=Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,'value').set;
                s.call(e,v); e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));};
              set('UserName','13800000000'); set('gsxtp','WrongPass-Probe');
              const b=document.getElementById('btn_login'); if(b) b.click();
            }""")
        except Exception as exc:
            print("提交失败:", str(exc)[:100])
        time.sleep(5)
        try:
            info2 = page.evaluate(DUMP)
            print("\n=== 提交后 ===")
            print(json.dumps(info2, ensure_ascii=False, indent=2)[:4000])
        except Exception as exc:
            print("读状态失败:", str(exc)[:120])
        shot = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "probe_out", "gsxt_login_probe.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        try:
            page.screenshot(path=shot, full_page=False)
            print("截图:", shot)
        except Exception as exc:
            print("截图失败:", exc)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
