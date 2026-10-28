# -*- coding: utf-8 -*-
"""真机验证（第六轮）：
A) gsxt 从上级目录（samr）跳转进入，不再是白页；
B) wenshu 打开首页 -> 自跳转不报错 -> 高级检索表单可用；
C) wenshu 自动登录：找到登录窗、填入账号密码、提交、给出明确结论；
D) 日期弹窗：连续展开 3 次，统计成功率。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop
from auth import autologin
from core import nav
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
    print("== A) gsxt 上级目录跳转 ==")
    res = nav.goto_via_landing(page, "gsxt", log=print,
                               timeout_ms=60000)
    print("  跳转结果 ok=%s reason=%s" % (res.get("ok"), res.get("reason", "")))
    # 链接带 target=_blank 时会开新标签页，后续要在**新页面**上判断
    target = res.get("page") or page
    st = nav.nav_state(target)
    print("  落地状态: url=%s title=%s len=%s blank=%s"
          % (str(st.get("url"))[:70], str(st.get("title"))[:30],
             st.get("len"), st.get("blank")))
    ok = safe_eval(target, "()=>{const e=document.getElementById('keyword');"
                           "return !!(e&&e.getBoundingClientRect().width>0);}")
    print("  搜索框可见: %s" % ok)
    if ok:
        try:
            page.screenshot(path=os.path.join(OUT, "gsxt_跳转成功.png"))
            print("  截图已保存")
        except Exception:
            pass


def part_b(page):
    print("\n" + "=" * 72)
    print("== B) wenshu 首页 + 高级检索 ==")
    try:
        ok = nav.goto(page, "https://wenshu.court.gov.cn/", timeout_ms=60000,
                      log=print)
        print("  goto 返回:", ok)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:120])
    time.sleep(7)
    st = safe_eval(page, """()=>({url:location.href,title:document.title||'',
        adv:!!document.querySelector('.advenced-search'),
        s17:!!document.querySelector('#s17'), qb:!!document.querySelector('#qbValue')})""")
    print("  状态:", st)
    # 点高级检索
    box = safe_eval(page, """(cls)=>{const d=document.querySelector(cls);
      if(!d) return null; const b=d.getBoundingClientRect();
      if(b.width<10||b.height<10) return null;
      return {x:b.x+b.width/2,y:b.y+b.height/2};}""", ".advenced-search")
    print("  高级检索入口坐标:", box)
    if box:
        page.mouse.click(box["x"], box["y"])
        time.sleep(3)
        vis = safe_eval(page, "()=>{const i=document.querySelector('#s17');"
                              "return !!(i&&i.getClientRects().length);}")
        print("  表单展开后 #s17 可见:", vis)


def part_c(page):
    print("\n" + "=" * 72)
    print("== C) wenshu 自动登录（真机，提交用假密码）==")
    try:
        nav.goto(page, "https://wenshu.court.gov.cn/", timeout_ms=60000, log=print)
    except Exception as exc:
        print("  goto 异常:", str(exc).splitlines()[0][:100])
    time.sleep(6)
    # 必须先点「登录」，登录 iframe 才会挂载
    print("  点登录:", autologin._open_wenshu_login(page, timeout=15))
    time.sleep(3)
    frame = autologin._find_wenshu_login_frame(page, timeout=25)
    print("  找到登录窗:", (frame.url[:90] if frame is not None else None))
    if frame is None:
        print("  ✘ 没找到登录窗")
        return
    # 手动走一遍：找密码框 -> 填 -> 提交 -> 判定
    has_pw = False
    try:
        has_pw = bool(frame.wait_for_selector("input[type=password]", timeout=5000))
    except Exception as exc:
        print("  查密码框异常:", str(exc).splitlines()[0][:80])
    print("  登录窗内有密码框:", has_pw)
    ok_user = autologin._fill(frame, "手机", "13800000000", kind="account")
    ok_pass = autologin._fill(frame, "", "Dummy-Pass-9", kind="password")
    print("  填账号=%s 填密码=%s" % (ok_user, ok_pass))
    vals = safe_eval(frame, """()=>{const u=document.querySelector('input[name=username]');
      const p=document.querySelector('input[type=password]');
      return {u:u?u.value:'', p: p?'len='+String(p.value||'').length:''};}""")
    print("  回读输入框:", vals)
    sub = autologin._submit_wenshu(frame, print)
    print("  提交:", sub)
    time.sleep(6)
    state, msg = autologin._ws_judge(page, frame, print)
    print("  判定: %s / %s" % (state, msg))
    # 看看登录窗里有没有图形验证码可识别
    cap = safe_eval(frame, """()=>{
      const imgs=[...document.querySelectorAll('img')].map(i=>({src:(i.src||'').slice(-60),
        w:i.naturalWidth,h:i.naturalHeight,cls:String(i.className||'').slice(0,30),
        id:i.id||'', r:i.getBoundingClientRect().width+'x'+i.getBoundingClientRect().height}))
        .filter(i=>i.w>0);
      const captchaEls=[...document.querySelectorAll('div,span,i,canvas')]
        .filter(e=>/captcha|verify|验证|滑块|拖动|点选/i.test(
          (e.className||'')+' '+(e.id||'')+' '+(e.innerText||'').slice(0,10)))
        .map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,45),
          t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,20),
          r:e.getBoundingClientRect().width+'x'+e.getBoundingClientRect().height}));
      return {imgs:imgs.slice(0,12), captchaEls:captchaEls.slice(0,12)};}""")
    if cap:
        print("  登录窗可见图片:")
        for i in cap.get("imgs", []):
            print("     w=%-4s h=%-4s r=%-12s cls=%-26s src=%s"
                  % (i["w"], i["h"], i["r"], i["cls"][:26], i["src"][:44]))
        print("  captcha 类元素:")
        for c in cap.get("captchaEls", []):
            print("     %-6s %-46s %-12s %s" % (c["tag"], c["cls"][:46], c["r"], c["t"]))


def part_d():
    print("\n" + "=" * 72)
    print("== D) 日期弹窗连开 3 次 ==")
    ok_n = 0
    for i in range(3):
        ok = desktop.open_date_popup(print)
        print("  第 %d 次: %s" % (i + 1, ok))
        if ok:
            ok_n += 1
        desktop.close_date_popup()
        time.sleep(1.0)
    print("  成功率: %d/3" % ok_n)


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
    part_d()


if __name__ == "__main__":
    main()
