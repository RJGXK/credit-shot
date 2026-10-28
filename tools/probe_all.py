# -*- coding: utf-8 -*-
"""第四轮探测：
A) 各站点首页上的站内链接（用于「从上级目录跳转」的落地配置）；
B) gsxt 的图形验证码弹窗 #popup-captcha 结构与刷新按钮；
C) wenshu 登录 frame 的出现时机、账号密码框与验证码元素。
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


def home_links(page, host_filter):
    r = safe_eval(page, """(arg)=>[...document.querySelectorAll('a[href]')]
        .map(a=>({href:a.href, t:(a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,24)}))
        .filter(x=>x.href.indexOf(arg.kw)>=0)
        .slice(0,25)""", {"kw": host_filter})
    return r or []


def part_a(page):
    print("\n" + "=" * 72)
    print("== A) 站内链接盘点 ==")
    cases = [
        ("信用中国首页", "https://www.creditchina.gov.cn/", "creditchina.gov.cn"),
        ("政采网首页", "https://www.ccgp.gov.cn/", "ccgp.gov.cn"),
        ("住建部首页", "https://jzsc.mohurd.gov.cn/home", "mohurd.gov.cn"),
        ("军队采购首页", "https://www.plap.mil.cn/freecms-glht/site/juncai/jdjc/index.html", "plap.mil.cn"),
        ("失信被执行人", "https://zxgk.court.gov.cn/shixin/", "zxgk.court.gov.cn"),
        ("samr 首页", "https://www.samr.gov.cn/", "gsxt.gov.cn"),
    ]
    for name, url, kw in cases:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print("  %-14s goto 异常: %s" % (name, str(exc).splitlines()[0][:80]))
            continue
        time.sleep(4)
        st = safe_eval(page, "()=>({t:document.title||'',l:(document.body?(document.body.innerText||'').length:0)})")
        links = home_links(page, kw)
        print("  %-14s title=%-28s len=%-6s 链接数=%d" % (name, str(st.get("t"))[:28], st.get("l"), len(links)))
        for x in links[:12]:
            print("       %-58s %s" % (x["href"][:58], x["t"]))


def part_b(page):
    print("\n" + "=" * 72)
    print("== B) gsxt 图形验证码弹窗 ==")
    for attempt in range(3):
        try:
            page.goto("https://www.gsxt.gov.cn/index.html",
                      wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(7)
        ok = safe_eval(page, "()=>{const e=document.getElementById('keyword');"
                             "return !!(e&&e.getBoundingClientRect().width>0);}")
        if ok:
            break
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
    time.sleep(7)
    info = safe_eval(page, """()=>{
      const p=document.getElementById('popup-captcha');
      const scope=p||document;
      const imgs=[...scope.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-60),
        w:i.naturalWidth,h:i.naturalHeight,id:i.id||'',
        r:i.getBoundingClientRect().width+'x'+i.getBoundingClientRect().height}));
      const ins=[...scope.querySelectorAll('input')].map(i=>({t:i.type||'',id:i.id||'',
        ph:i.placeholder||'',vis:i.getBoundingClientRect().width>0}));
      const btns=[...scope.querySelectorAll('button,a,span,div,i')].map(e=>({
        t:(e.innerText||'').trim().slice(0,14), id:e.id||'',
        cls:String(e.className||'').slice(0,40),
        r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}))
        .filter(x=>x.r!=='0x0');
      const gt=[...document.querySelectorAll('[class*=geetest]')].map(e=>({
        cls:String(e.className||'').slice(0,55),
        r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height,
        t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30)}));
      return {hasPopup:!!p, popupR:p?p.getBoundingClientRect().width+'x'+p.getBoundingClientRect().height:'',
              imgs, ins, btns:btns.slice(0,20), gt:gt.slice(0,14),
              body:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)};}""")
    if not info:
        print("  读取失败")
        return
    print("  有 popup-captcha:", info.get("hasPopup"), info.get("popupR"))
    print("  弹窗内图片:", info.get("imgs"))
    print("  弹窗内输入框:", info.get("ins"))
    print("  弹窗内可点元素:", info.get("btns"))
    print("  geetest 元素:")
    for g in info.get("gt", []):
        print("     %-58s %-12s %s" % (g["cls"][:58], g["r"], g["t"]))
    print("  body:", info.get("body"))


def part_c(page):
    print("\n" + "=" * 72)
    print("== C) wenshu 登录 frame 时机与验证码 ==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception:
        pass
    time.sleep(6)
    # 站点从 / 会自跳到 /website/wenshu/xxx/index.html —— 记下这个规律
    print("  首页 url:", page.url)
    print("  高级检索存在:", bool(safe_eval(page, "()=>!!document.querySelector('.advenced-search')")))
    # 点登录
    page.evaluate("""()=>{for(const x of document.querySelectorAll('a,span,div,li,button')){
        const t=(x.innerText||'').trim();
        if(!t||t.length>6||x.children.length>0) continue;
        if(!/^登录$|^登\\s*录$|^登录\\/?注册$/.test(t)) continue;
        const b=x.getBoundingClientRect(); if(b.width<4||b.height<4) continue;
        x.click(); return true;} return false;}""")
    for i in range(12):
        time.sleep(2)
        fr = page.frames
        acc = [f for f in fr if "account.court.gov.cn" in (f.url or "")]
        haspw = False
        for f in acc:
            try:
                haspw = haspw or bool(f.query_selector("input[type=password]", timeout=1000))
            except Exception:
                pass
        print("  +%2ds frames=%d account=%d pw=%s" % ((i + 1) * 2, len(fr), len(acc), haspw))
        if haspw:
            break
    for f in page.frames:
        if "account.court.gov.cn" not in (f.url or ""):
            continue
        d = safe_eval(f, """()=>({
          url:location.href,
          ins:[...document.querySelectorAll('input')].map(i=>({t:i.type||'',n:i.name||'',
             id:i.id||'',ph:i.placeholder||'',cls:String(i.className||'').slice(0,26),
             vis:i.getBoundingClientRect().width>0})),
          captcha:[...document.querySelectorAll('div,span,i,canvas,img,a')]
            .filter(e=>/captcha|verify|nc_|btn|刷新|换一张/i.test(
               (e.className||'')+' '+(e.id||'')+' '+(e.innerText||'').slice(0,12)))
            .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,45),id:e.id||'',
               t:(e.innerText||'').trim().slice(0,14),
               r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height})).slice(0,22),
          scripts:[...document.querySelectorAll('script[src]')].map(s=>s.src.slice(-70)).slice(0,12)
        })""")
        if not d:
            continue
        print("  iframe %s" % str(d.get("url"))[:80])
        print("    输入框:")
        for i in d.get("ins", []):
            print("      type=%-8s name=%-14s id=%-12s ph=%-12s vis=%s" %
                  (i["t"], i["n"][:14], i["id"][:12], i["ph"][:12], i["vis"]))
        print("    captcha/按钮类:")
        for c in d.get("captcha", []):
            print("      %-6s %-46s %-10s %s" % (c["tag"], c["cls"][:46], c["r"], c["t"]))
        print("    script:", d.get("scripts"))


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        part_a(page)
        part_b(page)
        part_c(page)
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
