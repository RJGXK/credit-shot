# -*- coding: utf-8 -*-
"""深挖：
1) wenshu 新版登录页（?open=login）里账号密码表单到底在哪、长什么样；
2) gsxt 的登录弹窗与图形验证码结构。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def dump(target, label):
    """把一个 page/frame 里的表单元素全量倒出来。"""
    try:
        info = target.evaluate("""()=>{
          const ins=[...document.querySelectorAll('input,textarea,button')]
            .map(e=>{const b=e.getBoundingClientRect();
              return {tag:e.tagName, type:e.type||'', name:e.name||'', id:e.id||'',
                      ph:e.placeholder||'', cls:String(e.className||'').slice(0,50),
                      txt:(e.innerText||e.value||'').trim().slice(0,20),
                      vis:b.width>0&&b.height>0};});
          const imgs=[...document.querySelectorAll('img')]
            .map(i=>({src:(i.src||'').slice(-70), w:i.naturalWidth, h:i.naturalHeight,
                      id:i.id||'', cls:String(i.className||'').slice(0,40)}));
          const txts=[...document.querySelectorAll('a,span,div,li,label,p,h1,h2,h3')]
            .map(e=>({t:(e.innerText||'').trim(), cls:String(e.className||'').slice(0,40)}))
            .filter(x=>x.t&&x.t.length<=12&&x.t.length>0);
          return {url:location.href, title:document.title||'',
                  body:(document.body?document.body.innerText:'').replace(/\\s+/g,' ').slice(0,300),
                  ins, imgs, txts:txts.slice(0,40)};
        }""")
    except Exception as exc:
        print("   读取失败:", str(exc).splitlines()[0][:120])
        return None
    print("  [%s] url=%s title=%s" % (label, str(info.get("url", ""))[:90], info.get("title", "")))
    print("   body: %s" % info.get("body", "")[:220])
    print("   表单元素:")
    for i in info.get("ins", []):
        print("     %s type=%-8s name=%-16s id=%-14s ph=%-14s vis=%s txt=%r cls=%s"
              % (i["tag"], i["type"], i["name"][:16], i["id"][:14], i["ph"][:14],
                 i["vis"], i["txt"], i["cls"][:24]))
    print("   图片:")
    for i in info.get("imgs", [])[:12]:
        print("     w=%-4s h=%-4s id=%-14s src=%s" % (i["w"], i["h"], i["id"][:14], i["src"][:64]))
    print("   文本:")
    print("     %s" % " | ".join(t["t"] for t in info.get("txts", []))[:400])
    return info


def wenshu(page):
    print("\n" + "=" * 70)
    print("== wenshu 新版登录页 ==")
    try:
        page.goto("https://wenshu.court.gov.cn/", wait_until="domcontentloaded", timeout=45000)
    except Exception as exc:
        print("  goto 异常(站点自跳):", str(exc).splitlines()[0][:110])
    time.sleep(5)
    print("  主页 frames:")
    for f in page.frames:
        print("    - %s" % str(f.url)[:110])
    # 点登录
    page.evaluate("""()=>{for(const x of document.querySelectorAll('a,span,div,li,button')){
        const t=(x.innerText||'').trim();
        if(!t||t.length>6||x.children.length>0) continue;
        if(!/^登录$|^登\\s*录$|^登录\\/?注册$/.test(t)) continue;
        const b=x.getBoundingClientRect(); if(b.width<4||b.height<4) continue;
        x.click(); return true;} return false;}""")
    time.sleep(4)
    print("  点登录后 url:", page.url)
    # 等 iframe 渲染
    for i in range(8):
        time.sleep(2)
        fr = page.frames
        acc = [f for f in fr if "account.court.gov.cn" in (f.url or "")]
        print("  +%ds frames=%d account=%d" % ((i + 1) * 2, len(fr), len(acc)))
        for f in acc:
            try:
                pw = f.query_selector("input[type=password]", timeout=1200)
            except Exception:
                pw = None
            if pw:
                print("    -> 出现密码框！frame=%s" % f.url[:90])
                break
    print("  最终 frames:")
    for f in page.frames:
        print("    - %s" % str(f.url)[:110])
    dump(page, "主页面")
    for f in page.frames:
        if "account.court.gov.cn" in (f.url or ""):
            dump(f, "iframe")
    # 在登录 iframe 里找「账号密码登录」tab
    for f in page.frames:
        if "account.court.gov.cn" not in (f.url or ""):
            continue
        print("\n  -- iframe 内路由切换 --", f.url[:90])
        for label in ("账号密码登录", "密码登录", "账号登录", "短信登录", "密码"):
            r = f.evaluate("""(t)=>{const norm=s=>(s||'').replace(/\\s+/g,'');
              const els=[...document.querySelectorAll('a,span,div,li,label,button')];
              const h=els.find(e=>norm(e.innerText||e.textContent||'')===norm(t)
                 || (norm(e.innerText||e.textContent||'').indexOf(norm(t))>=0
                     && norm(e.innerText||e.textContent||'').length<=norm(t).length+3));
              if(!h) return 'NONE';
              h.click(); return 'CLICK:'+(h.innerText||h.textContent||'').trim().slice(0,20);}""", label)
            print("     点「%s」-> %s" % (label, r))
            time.sleep(2.5)
            try:
                pw = f.query_selector("input[type=password]", timeout=1200)
            except Exception:
                pw = None
            print("        密码框=%s" % bool(pw))
            if pw:
                dump(f, "切tab后")
                break


def gsxt(page):
    print("\n" + "=" * 70)
    print("== gsxt 登录弹窗 ==")
    for attempt in range(3):
        try:
            page.goto("https://www.gsxt.gov.cn/index.html",
                      wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(6)
        ok = page.evaluate("()=>{const e=document.getElementById('keyword');"
                            "return !!(e&&e.getBoundingClientRect().width>0);}")
        print("  第%d次 搜索框就绪=%s" % (attempt + 1, ok))
        if ok:
            break
    dump(page, "gsxt首页")
    # 点「登录」
    r = page.evaluate("""()=>{const norm=s=>(s||'').replace(/\\s+/g,'');
      const els=[...document.querySelectorAll('a,span,div,li,button')];
      const h=els.find(e=>norm(e.innerText||e.textContent||'')==='登录'
         && e.getBoundingClientRect().width>0);
      if(!h) return 'NONE';
      h.click(); return 'CLICK';}""")
    print("  点登录:", r)
    time.sleep(5)
    print("  url:", page.url)
    dump(page, "点登录后")
    for f in page.frames:
        if f == page.main_frame:
            continue
        dump(f, "iframe")
    # 找弹窗里的输入框并填
    for f in list(page.frames):
        try:
            ins = f.evaluate("""()=>[...document.querySelectorAll('input')]
              .map(e=>({t:e.type||'',ph:e.placeholder||'',id:e.id||'',name:e.name||''}))""")
        except Exception:
            continue
        if ins:
            print("  frame %s 输入框: %s" % (str(f.url)[:60], ins))


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
