# -*- coding: utf-8 -*-
"""深挖 gsxt 的进入方式（瑞数 Environment Checking 白页）与 wenshu 登录窗结构。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def st(page):
    try:
        return page.evaluate("""()=>({url:location.href, title:document.title||'',
          len:(document.body?(document.body.innerText||'').length:0),
          head:(document.body?(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,150):''),
          kw:!!document.getElementById('keyword')})""")
    except Exception as exc:
        return {"err": str(exc).splitlines()[0][:100]}


def gsxt_direct_wait(page, seconds):
    """直连后长等，观察瑞数是否自动放行。"""
    print("\n== gsxt 直连 + 长等 %ds ==" % seconds)
    try:
        page.goto("https://www.gsxt.gov.cn/index.html",
                  wait_until="domcontentloaded", timeout=45000)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:100])
    for i in range(1, seconds // 3 + 1):
        time.sleep(3)
        s = st(page)
        print("  +%2ds url=%s title=%-28s len=%-6s kw=%s"
              % (i * 3, str(s.get("url", ""))[:46], str(s.get("title", ""))[:28],
                 s.get("len", "?"), s.get("kw", "?")))
        if s.get("kw") or (s.get("len") or 0) > 500:
            print("  -> 放行！")
            return True
    return False


def gsxt_reload(page):
    """瑞数已种下 cookie，再 reload 一次。"""
    print("\n== gsxt 直连后 reload ==")
    try:
        page.goto("https://www.gsxt.gov.cn/index.html",
                  wait_until="domcontentloaded", timeout=45000)
    except Exception:
        pass
    time.sleep(4)
    print("  reload 前:", st(page))
    try:
        page.reload(wait_until="domcontentloaded", timeout=45000)
    except Exception as exc:
        print("  reload 异常:", str(exc).splitlines()[0][:100])
    time.sleep(6)
    print("  reload 后:", st(page))


def gsxt_via_samr_real_click(page):
    """在 samr 页面用 Playwright 真实点击链接（不是 JS click）。"""
    print("\n== gsxt 经 samr 真实点击 ==")
    try:
        page.goto("https://www.samr.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:100])
    time.sleep(3)
    links = page.evaluate("""()=>[...document.querySelectorAll('a[href]')]
      .filter(a=>a.href.indexOf('gsxt.gov.cn')>=0)
      .map(a=>({href:a.href, text:(a.innerText||'').trim().slice(0,30),
                target:a.target||'', onclick:!!a.onclick}))""")
    print("  samr 上指向 gsxt 的链接:", links)
    if not links:
        return
    # 用真实鼠标点第一个
    try:
        el = page.locator("a[href*='gsxt.gov.cn']").first
        with page.context.expect_page(timeout=8000) as ci:
            el.click(timeout=8000)
            newp = ci.value
        print("  打开了新标签页:", newp.url)
        newp.wait_for_load_state("domcontentloaded", timeout=30000)
        time.sleep(5)
        print("  新页状态:", st(newp))
    except Exception as exc:
        print("  真实点击异常:", str(exc).splitlines()[0][:130])
        time.sleep(3)
        print("  当前页状态:", st(page))


def wenshu_login(page):
    """查看裁判文书网的登录窗结构。"""
    print("\n== wenshu 登录窗结构 ==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded",
                  timeout=45000)
    except Exception as exc:
        print("  goto 异常(可能站点自跳):", str(exc).splitlines()[0][:120])
    time.sleep(6)
    print("  主页:", st(page))
    print("  frames:")
    for f in page.frames:
        try:
            has_pw = f.query_selector("input[type=password]", timeout=1500)
        except Exception:
            has_pw = None
        print("    - %s | pw=%s" % (str(f.url)[:100], bool(has_pw)))
    # 点「登录」
    js = """()=>{for(const x of document.querySelectorAll('a,span,div,li,button')){
        const t=(x.innerText||'').trim();
        if(!t||t.length>6||x.children.length>0) continue;
        if(!/^登录$|^登\\s*录$|^登录\\/?注册$/.test(t)) continue;
        const b=x.getBoundingClientRect(); if(b.width<4||b.height<4) continue;
        x.click(); return 'CLICK:'+t;} return 'NONE';}"""
    print("  点登录:", page.evaluate(js))
    time.sleep(6)
    print("  点后主页:", st(page))
    print("  点后 frames:")
    for f in page.frames:
        try:
            has_pw = f.query_selector("input[type=password]", timeout=1500)
        except Exception:
            has_pw = None
        if "account.court.gov.cn" in (f.url or ""):
            print("    * %s | pw=%s" % (str(f.url)[:110], bool(has_pw)))
            if has_pw:
                try:
                    info = f.evaluate("""()=>{
                      const ins=[...document.querySelectorAll('input,textarea')];
                      return ins.map(e=>({tag:e.tagName, type:e.type||'',
                        name:e.name||'', id:e.id||'',
                        ph:e.placeholder||'', cls:e.className||''}));
                    }""")
                    print("      输入框:", info)
                    imgs = f.evaluate("""()=>[...document.querySelectorAll('img')]
                      .map(i=>({src:(i.src||'').slice(0,90), w:i.naturalWidth,
                                 h:i.naturalHeight, id:i.id||'', cls:i.className||''}))""")
                    print("      图片:", imgs)
                    btns = f.evaluate("""()=>[...document.querySelectorAll('button,a,div,span')]
                      .map(e=>({t:(e.innerText||'').trim().slice(0,16),
                                cls:e.className||''}))
                      .filter(x=>x.t&&x.t.length<=8)""")
                    print("      文本元素:", btns[:30])
                except Exception as exc:
                    print("      读取失败:", str(exc).splitlines()[0][:100])


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        gsxt_direct_wait(page, 30)
        gsxt_reload(page)
        gsxt_via_samr_real_click(page)
        wenshu_login(page)
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
