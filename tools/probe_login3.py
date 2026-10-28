# -*- coding: utf-8 -*-
"""第三轮精确探测：
1) wenshu：站点自跳转的落点、高级检索表单、登录框内的验证码元素；
2) gsxt：登录弹窗结构与图形验证码（含刷新机制）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def safe_eval(page, js, arg=None, tries=6):
    for _ in range(tries):
        try:
            return page.evaluate(js) if arg is None else page.evaluate(js, arg)
        except Exception:
            time.sleep(1.2)
    return None


def wenshu(page):
    print("\n" + "=" * 72)
    print("== wenshu 完整链路 ==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:130])
    time.sleep(8)
    print("  当前 url:", page.url)
    st = safe_eval(page, """()=>({url:location.href,title:document.title||'',
        adv:!!document.querySelector('.advenced-search'),
        advs:[...document.querySelectorAll('[class*=advenc],[class*=advanced],[class*=search]')]
               .map(e=>e.className).slice(0,10),
        s17:!!document.querySelector('#s17'),
        qb:!!document.querySelector('#qbValue'),
        inputs:[...document.querySelectorAll('input')].map(e=>({id:e.id,name:e.name,
                 ph:e.placeholder||'',cls:String(e.className||'').slice(0,30)})).slice(0,25)})""")
    print("  状态:", st)
    # 列出高级检索相关按钮
    btns = safe_eval(page, """()=>[...document.querySelectorAll('a,span,div,li,button')]
        .filter(e=>/高级检索|高级搜索|检索/.test((e.innerText||'').trim()))
        .map(e=>({t:(e.innerText||'').trim().slice(0,14),
                  cls:String(e.className||'').slice(0,40)}))""")
    print("  检索类元素:", btns)

    # 点登录
    page.evaluate("""()=>{for(const x of document.querySelectorAll('a,span,div,li,button')){
        const t=(x.innerText||'').trim();
        if(!t||t.length>6||x.children.length>0) continue;
        if(!/^登录$|^登\\s*录$|^登录\\/?注册$/.test(t)) continue;
        const b=x.getBoundingClientRect(); if(b.width<4||b.height<4) continue;
        x.click(); return true;} return false;}""")
    time.sleep(8)
    print("  点登录后 frames:")
    for f in page.frames:
        print("    - %s" % str(f.url)[:100])
    for f in page.frames:
        if "account.court.gov.cn" not in (f.url or ""):
            continue
        # 详细看验证码元素
        info = safe_eval(f, """()=>{
          const all=[...document.querySelectorAll('*')];
          const canv=all.filter(e=>e.tagName==='CANVAS').map(c=>({id:c.id||'',
              w:c.width,h:c.height, cls:String(c.className||'').slice(0,30),
              r:(c.getBoundingClientRect().width)+'x'+(c.getBoundingClientRect().height)}));
          const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-60),
              w:i.naturalWidth,h:i.naturalHeight,cls:String(i.className||'').slice(0,30),
              id:i.id||''}));
          const al=all.filter(e=>/captcha|verify|验证|滑块|拖动|点选/i.test(
              (e.className||'')+' '+(e.id||'')+' '+(e.innerText||'').slice(0,20)))
            .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,40),
                      id:e.id||'',t:(e.innerText||'').trim().slice(0,16)}));
          const sc=all.filter(e=>e.tagName==='SCRIPT').map(s=>(s.src||'inline').slice(0,90)).slice(0,10);
          return {canv, imgs:imgs.slice(0,10), al:al.slice(0,20), sc,
                  txt:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,400)};
        }""")
        print("  iframe %s 详情:" % str(f.url)[:60])
        if info:
            print("    canvas:", info.get("canv"))
            print("    captcha类元素:", info.get("al"))
            print("    script:", info.get("sc"))
            print("    文本:", info.get("txt"))
        # 尝试点一下验证码触发
        r = safe_eval(f, """()=>{
          const els=[...document.querySelectorAll('div,span,i,img,canvas')];
          const h=els.find(e=>/captcha|verify/i.test((e.className||'')+' '+(e.id||'')));
          if(!h) return 'NONE';
          h.click(); return 'CLICK:'+(h.className||h.id||h.tagName);}""")
        print("    点 captcha 容器:", r)
        time.sleep(3)
        info2 = safe_eval(f, """()=>{
          const canv=[...document.querySelectorAll('canvas')].map(c=>({w:c.width,h:c.height,
            r:c.getBoundingClientRect().width+'x'+c.getBoundingClientRect().height}));
          const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-50),
            w:i.naturalWidth,h:i.naturalHeight}));
          return {canv, imgs:imgs.slice(0,12),
            al:[...document.querySelectorAll('div,span,i')]
              .filter(e=>/captcha|verify|验证/i.test((e.className||'')+' '+(e.id||'')))
              .map(e=>(e.className||e.id||'').slice(0,40)).slice(0,12)};}""")
        print("    点后 canvas:", info2.get("canv") if info2 else None)
        print("    点后 captcha元素:", info2.get("al") if info2 else None)
        print("    点后 img:", info2.get("imgs") if info2 else None)


def gsxt(page):
    print("\n" + "=" * 72)
    print("== gsxt 登录与验证码 ==")
    for attempt in range(3):
        try:
            page.goto("https://www.gsxt.gov.cn/index.html",
                      wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(7)
        ok = safe_eval(page, "()=>{const e=document.getElementById('keyword');"
                             "return !!(e&&e.getBoundingClientRect().width>0);}")
        print("  第%d次 就绪=%s" % (attempt + 1, ok))
        if ok:
            break
    # 查搜索时的验证码：先填关键词点查询
    print("  填关键词并点查询...")
    safe_eval(page, """()=>{const e=document.getElementById('keyword');
      if(e){e.focus();
        const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(e,'中瑞盛世（北京）建筑有限公司');
        e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true}));}
      return 'OK';}""")
    time.sleep(1)
    safe_eval(page, """()=>{const els=[...document.querySelectorAll('button,a,input,div,span')];
      const b=els.find(e=>(e.innerText||e.value||'').replace(/\\s+/g,'')==='查询'
        && e.getBoundingClientRect().width>0);
      if(b) b.click(); return 'CLICK';}""")
    time.sleep(6)
    cap = safe_eval(page, """()=>{
      const all=[...document.querySelectorAll('*')];
      const gt=all.filter(e=>/geetest|captcha|verify|验证|滑块/i.test(
          (e.className||'')+' '+(e.id||'')+' '+(e.innerText||'').slice(0,16)))
        .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,50),id:e.id||'',
                  t:(e.innerText||'').trim().slice(0,18),
                  r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}));
      const ifr=[...document.querySelectorAll('iframe')].map(f=>({src:(f.src||'').slice(-70),
        r:f.getBoundingClientRect().width+'x'+f.getBoundingClientRect().height}));
      const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-55),
        w:i.naturalWidth,h:i.naturalHeight,cls:String(i.className||'').slice(0,30)}));
      return {gt:gt.slice(0,15), ifr, imgs:imgs.slice(0,10),
        body:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,300)};}""")
    print("  查询后 captcha 相关:", cap.get("gt") if cap else None)
    print("  查询后 iframe:", cap.get("ifr") if cap else None)
    print("  查询后 img:", cap.get("imgs") if cap else None)
    print("  查询后 body:", cap.get("body") if cap else None)
    # 登录弹窗
    r = safe_eval(page, """()=>{const norm=s=>(s||'').replace(/\\s+/g,'');
      const els=[...document.querySelectorAll('a,span,div,li,button')];
      const h=els.find(e=>norm(e.innerText||e.textContent||'')==='登录'
         && e.getBoundingClientRect().width>0);
      if(!h) return 'NONE';
      h.click(); return 'CLICK';}""")
    print("  点登录:", r)
    time.sleep(6)
    lg = safe_eval(page, """()=>{
      const all=[...document.querySelectorAll('*')];
      const dlg=all.filter(e=>/login|登录/i.test((e.className||'')+' '+(e.id||'')))
        .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,50),id:e.id||'',
                  vis:e.getBoundingClientRect().width>0}));
      const ins=[...document.querySelectorAll('input')].map(i=>({t:i.type||'',ph:i.placeholder||'',
        id:i.id||'',name:i.name||'',vis:i.getBoundingClientRect().width>0}));
      const ifr=[...document.querySelectorAll('iframe')].map(f=>({src:(f.src||'').slice(-70),
        r:f.getBoundingClientRect().width+'x'+f.getBoundingClientRect().height}));
      const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-55),
        w:i.naturalWidth,h:i.naturalHeight,cls:String(i.className||'').slice(0,30)}));
      return {dlg:dlg.slice(0,12), ins, ifr, imgs:imgs.slice(0,12),
        body:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,300)};}""")
    print("  登录相关元素:", lg.get("dlg") if lg else None)
    print("  登录输入框:", lg.get("ins") if lg else None)
    print("  登录 iframe:", lg.get("ifr") if lg else None)
    print("  登录 img:", lg.get("imgs") if lg else None)
    print("  登录 body:", lg.get("body") if lg else None)
    for f in page.frames:
        if f == page.main_frame:
            continue
        d = safe_eval(f, """()=>({url:location.href,
          ins:[...document.querySelectorAll('input')].map(i=>({t:i.type||'',ph:i.placeholder||'',
               id:i.id||'',name:i.name||''})),
          imgs:[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-50),
               w:i.naturalWidth,h:i.naturalHeight}))})""")
        if d:
            print("  frame %s:" % str(d.get("url", ""))[:60])
            print("    ins:", d.get("ins"))
            print("    imgs:", d.get("imgs"))


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        wenshu(page)
        gsxt(page)
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
