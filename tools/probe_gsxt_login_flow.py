# -*- coding: utf-8 -*-
"""真机探测 gsxt 登录链路：登录页在哪、表单结构、成功后的页面标志。"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "gsxt", log=print, timeout_ms=45000)
        p = res.get("page") or page
        time.sleep(2)

        # 1) 找到登录链接并点击
        r = p.evaluate("""()=>{
          const a=[...document.querySelectorAll('a')].find(e=>{
            const t=(e.innerText||'').replace(/\\s+/g,'').trim();
            return t==='登录';});
          if(!a) return 'NO_LINK';
          const href=a.href||'';
          a.click();
          return 'CLICK:'+href.slice(0,80);
        }""")
        print("登录链接:", r)
        time.sleep(5)

        # 2) 观察点击后的状态（可能同页弹窗，可能整页跳转）
        time.sleep(3)
        st = {}
        for attempt in range(4):
            try:
                st = p.evaluate("""()=>{
                  return {
                    url: location.href.slice(0, 90),
                    title: document.title,
                    hasUserName: !!document.getElementById('UserName'),
                    hasBtnLogin: !!document.getElementById('btn_login'),
                    loginBox: !!document.querySelector('.loginBox'),
                    head: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0, 150)
                  };
                }""")
                break
            except Exception:
                # 登录跳转进行中，上下文被销毁属正常，等一下重试
                time.sleep(2)
        print("点登录后:", json.dumps(st, ensure_ascii=False))

        # 3) 若整页跳转，等一会儿再看
        time.sleep(4)
        st2 = {}
        try:
            st2 = p.evaluate("""()=>{
              return {
                url: location.href.slice(0, 90),
                hasUserName: !!document.getElementById('UserName'),
                hasBtnLogin: !!document.getElementById('btn_login'),
                head: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0, 150)
              };
            }""")
        except Exception:
            pass
        print("再等 4s:", json.dumps(st2, ensure_ascii=False))

        # 4) 如果有登录表单，填入假账号看错误提示文案（判定词依据）
        if st2.get("hasUserName"):
            p.evaluate("""()=>{
              const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
              const u=document.getElementById('UserName');
              const pw=document.getElementById('gsxtp');
              s.call(u,'13800000000');
              u.dispatchEvent(new Event('input',{bubbles:true}));
              s.call(pw,'WrongPass-Test');
              pw.dispatchEvent(new Event('input',{bubbles:true}));
              const b=document.getElementById('btn_login');
              if(b) b.click();
            }""")
            time.sleep(4)
            try:
                err = p.evaluate("""()=>{
                  return {
                    head: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0, 200),
                    hasGeetest: !!document.querySelector('[class*=geetest]'),
                    url: location.href.slice(0, 90)
                  };
                }""")
                print("假账号提交后:", json.dumps(err, ensure_ascii=False))
            except Exception as exc:
                print("假账号提交后读状态失败:", str(exc)[:80])

        # 5) 登录成功页（如果之前登录过，profile 里可能有会话）——看首页标志
        p.goto("https://www.gsxt.gov.cn/index.html", wait_until="domcontentloaded",
               timeout=45000)
        time.sleep(5)
        home = p.evaluate("""()=>{
          return {
            url: location.href.slice(0, 90),
            head: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0, 250),
            hasLogout: /退出|注销/.test(document.body.innerText||''),
            hasWelcome: /欢迎|您好|个人中心|我的/.test(document.body.innerText||'')
          };
        }""")
        print("首页状态:", json.dumps(home, ensure_ascii=False))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
