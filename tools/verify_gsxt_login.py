# -*- coding: utf-8 -*-
"""真机验证 gsxt 自动登录链路（假密码）。

关注点：
  1) 从 samr 跳转进入 gsxt，搜索框可见；
  2) 点「登录」能打开 .loginBox 登录框；
  3) 账号密码能填进去；
  4) 提交后能判定出明确结论（极验点选 -> 需要人工 / 账号密码不正确 / 成功）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import autologin
from core import nav
from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def safe_eval(t, js, arg=None, tries=6):
    for _ in range(tries):
        try:
            return t.evaluate(js) if arg is None else t.evaluate(js, arg)
        except Exception:
            time.sleep(1.0)
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=print)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        print("\n== 1) 上级目录跳转 ==")
        res = nav.goto_via_landing(page, "gsxt", log=print, timeout_ms=60000)
        # 链接带 target=_blank 时会开新标签页，后续操作要切过去
        newp = res.get("page")
        if newp is not None:
            page = newp
            print("  已切换到新标签页")
        print("  ok=%s reason=%s" % (res.get("ok"), res.get("reason", "")))
        st = nav.nav_state(page)
        print("  url=%s title=%s len=%s" % (str(st.get("url"))[:70],
                                           str(st.get("title"))[:30], st.get("len")))
        print("  搜索框可见:", safe_eval(page,
              "()=>{const e=document.getElementById('keyword');"
              "return !!(e&&e.getBoundingClientRect().width>0);}"))

        print("\n== 2) 打开登录框 ==")
        ok = autologin._gsxt_open_login(page, print, timeout=15)
        print("  登录框打开:", ok)
        print("  #UserName 存在:", bool(safe_eval(page,
              "()=>{const e=document.getElementById('UserName');"
              "return !!(e&&e.getBoundingClientRect().width>0);}")))
        print("  #gsxtp 存在:", bool(safe_eval(page,
              "()=>{const e=document.getElementById('gsxtp');"
              "return !!(e&&e.getBoundingClientRect().width>0);}")))

        print("\n== 3) 填值 ==")
        r = autologin._gsxt_fill(page, "13800000000", "Dummy-Pass-9")
        print("  填值结果:", r)
        print("  回读:", safe_eval(page, """()=>{const u=document.getElementById('UserName');
          const p=document.getElementById('gsxtp');
          return {u:u?u.value:'', p:p?('len='+String(p.value||'').length):''};}"""))

        print("\n== 4) 提交并判定 ==")
        print("  提交:", autologin._gsxt_submit(page))
        time.sleep(8)
        state, msg = autologin._gsxt_judge(page, print)
        print("  判定: %s / %s" % (state, msg))
        cap = safe_eval(page, """()=>{
          const els=[...document.querySelectorAll('[class*=geetest],[class*=tianai]')]
            .filter(e=>{const b=e.getBoundingClientRect(); return b.width>80&&b.height>40;})
            .map(e=>({cls:String(e.className||'').slice(0,50),
              t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,24)}));
          return els.slice(0,8);}""")
        print("  可见验证码元素:")
        for c in cap or []:
            print("     %-52s %s" % (c["cls"], c["t"]))
        try:
            page.screenshot(path=os.path.join(OUT, "gsxt_登录后.png"))
            print("  截图已保存")
        except Exception:
            pass
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
