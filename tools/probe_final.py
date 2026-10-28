# -*- coding: utf-8 -*-
"""第五轮定向探测：
A) wenshu 点「登录」的可靠方式（元素 id / href），以及登录窗出现的判定；
B) gsxt 提交登录后的验证码形态、#popup-captcha 内容；
C) 裁判文书网高级检索表单在自跳后的可用性。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def safe_eval(t, js, arg=None, tries=8):
    for _ in range(tries):
        try:
            return t.evaluate(js) if arg is None else t.evaluate(js, arg)
        except Exception:
            time.sleep(1.0)
    return None


def part_a(page):
    print("\n" + "=" * 72)
    print("== A) wenshu 登录入口 ==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:120])
    time.sleep(6)
    print("  url:", page.url)
    # 列出所有含「登录」的元素及其 id/class/href
    items = safe_eval(page, """()=>[...document.querySelectorAll('a,span,div,li,button,i')]
        .filter(e=>/登录|注册/.test((e.innerText||'').trim()))
        .map(e=>({tag:e.tagName, t:(e.innerText||'').trim().slice(0,12),
                  id:e.id||'', cls:String(e.className||'').slice(0,40),
                  href:e.getAttribute('href')||'',
                  r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}))
        .filter(x=>x.t.length<=14).slice(0,20)""")
    print("  含「登录/注册」的元素:")
    for x in items or []:
        print("     %-6s t=%-8s id=%-12s href=%-28s r=%-12s cls=%s"
              % (x["tag"], x["t"], x["id"][:12], x["href"][:28], x["r"], x["cls"][:30]))
    # 用 id=loginLi 真实点击
    print("  尝试 #loginLi 真实点击…")
    try:
        el = page.query_selector("#loginLi", timeout=4000)
        print("    #loginLi 存在:", bool(el))
        if el:
            el.click(timeout=5000)
    except Exception as exc:
        print("    点击异常:", str(exc).splitlines()[0][:100])
    for i in range(10):
        time.sleep(2)
        fr = page.frames
        acc = [f for f in fr if "account.court.gov.cn" in (f.url or "")]
        print("  +%2ds url=%-58s frames=%d account=%d"
              % ((i + 1) * 2, page.url[:58], len(fr), len(acc)))
        if acc:
            break
    for f in page.frames:
        if "account.court.gov.cn" not in (f.url or ""):
            continue
        d = safe_eval(f, """()=>({
          url:location.href,
          ins:[...document.querySelectorAll('input')].map(i=>({t:i.type||'',n:i.name||'',
             id:i.id||'',ph:i.placeholder||'',cls:String(i.className||'').slice(0,26),
             vis:i.getBoundingClientRect().width>0})),
          captcha:[...document.querySelectorAll('div,span,i,canvas,img,a,button')]
            .filter(e=>/captcha|verify|nc_|刷新|换一张|滑块|拖动|点选/i.test(
               (e.className||'')+' '+(e.id||'')+' '+(e.innerText||'').slice(0,12)))
            .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,45),id:e.id||'',
               t:(e.innerText||'').trim().slice(0,14),
               r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height})).slice(0,25),
          body:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,220)
        })""")
        if not d:
            continue
        print("  iframe:", str(d.get("url"))[:90])
        print("    输入框:")
        for i in d.get("ins", []):
            print("      type=%-8s name=%-14s id=%-12s ph=%-12s vis=%s" %
                  (i["t"], i["n"][:14], i["id"][:12], i["ph"][:12], i["vis"]))
        print("    captcha/按钮:")
        for c in d.get("captcha", []):
            print("      %-6s %-46s %-12s %s" % (c["tag"], c["cls"][:46], c["r"], c["t"]))
        print("    body:", d.get("body"))


def part_b(page):
    print("\n" + "=" * 72)
    print("== B) gsxt 登录提交后的验证码 ==")
    for attempt in range(3):
        try:
            page.goto("https://www.gsxt.gov.cn/index.html",
                      wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(7)
        if safe_eval(page, "()=>{const e=document.getElementById('keyword');"
                           "return !!(e&&e.getBoundingClientRect().width>0);}"):
            break
    # 点登录
    print("  点登录:", safe_eval(page, """()=>{const norm=s=>(s||'').replace(/\\s+/g,'');
      const h=[...document.querySelectorAll('a,span,div,li,button')]
        .find(e=>norm(e.innerText||e.textContent||'')==='登录'
          && e.getBoundingClientRect().width>0);
      if(!h) return 'NONE'; h.click(); return 'CLICK';}"""))
    time.sleep(4)
    # 填账号密码（假的）
    print("  填假账号密码:", safe_eval(page, """()=>{
      const set=(id,v)=>{const e=document.getElementById(id); if(!e) return 'NO:'+id;
        e.focus();
        const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(e,v); e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true})); return 'OK';};
      return set('UserName','13800000000')+'/'+set('gsxtp','Dummy-123456');}"""))
    time.sleep(1)
    print("  点登录按钮:", safe_eval(page, """()=>{const b=document.getElementById('btn_login');
      if(!b) return 'NONE'; b.click(); return 'CLICK';}"""))
    time.sleep(7)
    info = safe_eval(page, """()=>{
      const all=[...document.querySelectorAll('*')];
      const gt=all.filter(e=>/geetest|captcha|verify/i.test((e.className||'')+' '+(e.id||'')))
        .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,55),id:e.id||'',
          t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,26),
          r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height,
          vis:e.getBoundingClientRect().width>0}));
      const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-55),
        w:i.naturalWidth,h:i.naturalHeight,cls:String(i.className||'').slice(0,26),
        r:i.getBoundingClientRect().width+'x'+i.getBoundingClientRect().height}));
      const pc=document.getElementById('popup-captcha');
      return {gt:gt.filter(x=>x.vis).slice(0,20), imgs:imgs.filter(x=>x.w>0).slice(0,14),
        pc: pc?{html:pc.outerHTML.slice(0,400), r:pc.getBoundingClientRect().width+'x'+pc.getBoundingClientRect().height}:null,
        body:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,260)};}""")
    if info:
        print("  可见 captcha 元素:")
        for g in info.get("gt", []):
            print("     %-6s %-56s %-12s %s" % (g["tag"], g["cls"][:56], g["r"], g["t"]))
        print("  图片:")
        for i in info.get("imgs", []):
            print("     w=%-4s h=%-4s r=%-12s cls=%-28s src=%s" %
                  (i["w"], i["h"], i["r"], i["cls"][:28], i["src"][:50]))
        print("  #popup-captcha:", (info.get("pc") or {}).get("r"))
        print("  body:", info.get("body"))


def part_c(page):
    print("\n" + "=" * 72)
    print("== C) wenshu 高级检索表单可用性（自跳后）==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:120])
    time.sleep(8)
    print("  url:", page.url)
    d = safe_eval(page, """()=>({url:location.href,title:document.title||'',
      adv:!!document.querySelector('.advenced-search'),
      advVis:(()=>{const e=document.querySelector('.advenced-search');
        return e?e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height:'';})(),
      s17:(()=>{const e=document.querySelector('#s17');
        return e?{v:e.value,r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}:null;})(),
      qb:(()=>{const e=document.querySelector('#qbValue');
        return e?{v:e.value,r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}:null;})(),
      body:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,200)})""")
    print("  ", d)
    # 试试高级检索入口的类名
    print("  adv 入口元素:")
    r = safe_eval(page, """()=>[...document.querySelectorAll('a,span,div,li,button')]
      .filter(e=>/高级检索|高级搜索/.test((e.innerText||'').trim()))
      .map(e=>({tag:e.tagName,t:(e.innerText||'').trim().slice(0,14),
                id:e.id||'',cls:String(e.className||'').slice(0,45),
                r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}))""")
    for x in r or []:
        print("     %-6s t=%-12s id=%-10s r=%-12s cls=%s" %
              (x["tag"], x["t"], x["id"][:10], x["r"], x["cls"][:45]))


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        part_c(page)
        part_a(page)
        part_b(page)
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
