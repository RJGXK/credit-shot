# -*- coding: utf-8 -*-
"""探针：从 gsxt 首页点「登录」进入实名认证子站，看清登录页结构。

直连 shiming.gsxt.gov.cn 会被瑞数 Environment Checking 拦成白页，
所以必须走「gsxt 首页 → 点登录」这条路（和程序一致）。

关注：
1. 登录页里有没有**图形验证码图片**（有 → 打码服务能自动过）；
2. 提交后弹的是**极验 geetest**（只能人工）还是别的；
3. 页面文字里有没有可作为「登录成功」标志的内容。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")

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
  out.geetest=[...document.querySelectorAll('[class*=geetest],[id*=geetest]')]
      .map(e=>{const b=e.getBoundingClientRect(); const st=getComputedStyle(e);
        return {cls:(e.className||'').toString().slice(0,50), id:e.id||'',
                w:Math.round(b.width), h:Math.round(b.height),
                disp:st.display, vis:st.visibility, op:st.opacity,
                shown:!!e.offsetParent};});
  out.captcha=[...document.querySelectorAll('[class*=captcha],[id*=captcha],[class*=yanzheng],[id*=yanzheng]')]
      .map(e=>{const b=e.getBoundingClientRect(); const st=getComputedStyle(e);
        return {tag:e.tagName, cls:(e.className||'').toString().slice(0,50),
                id:e.id||'', w:Math.round(b.width), h:Math.round(b.height),
                disp:st.display, shown:!!e.offsetParent,
                txt:(e.innerText||'').replace(/\\s+/g,' ').slice(0,60)};});
  out.text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,900);
  return out;
}
"""


def dump(page, tag):
    try:
        info = page.evaluate(DUMP)
    except Exception as exc:
        print("  读状态失败:", str(exc)[:120])
        return {}
    print("\n=== %s ===" % tag)
    print(json.dumps(info, ensure_ascii=False, indent=2)[:4000])
    return info


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "gsxt", log=print, timeout_ms=45000)
        p = res.get("page") or page
        time.sleep(3)
        dump(p, "gsxt 首页")

        print("\n--- 点首页的「登录」---")
        try:
            p.evaluate("""()=>{
              const els=[...document.querySelectorAll('a,span,div,li,button')];
              const hit=els.find(e=>(e.innerText||'').replace(/\\s+/g,'')==='登录');
              if(hit) hit.click();
            }""")
        except Exception as exc:
            print("点登录失败:", str(exc)[:100])
        time.sleep(6)
        for i in range(6):
            try:
                p.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(2)
            try:
                if p.evaluate("()=>!!document.getElementById('UserName')"):
                    break
            except Exception:
                continue
        info = dump(p, "登录页")

        # 提交一次假密码，看弹什么
        print("\n--- 提交假密码 ---")
        try:
            p.evaluate("""()=>{
              const set=(id,v)=>{const e=document.getElementById(id); if(!e) return;
                const s=Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,'value').set;
                s.call(e,v); e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));};
              set('UserName','13800000000'); set('gsxtp','WrongPass-Probe');
              const b=document.getElementById('btn_login'); if(b) b.click();
            }""")
        except Exception as exc:
            print("提交失败:", str(exc)[:120])
        time.sleep(6)
        dump(p, "提交后")

        shot = os.path.join(OUT, "gsxt_login_probe2.png")
        os.makedirs(OUT, exist_ok=True)
        try:
            p.screenshot(path=shot, full_page=False)
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
