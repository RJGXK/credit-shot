# -*- coding: utf-8 -*-
"""真机端到端（**不提交**）：跑完整 try_login 流程，只把「点提交」打桩。

验证点：
  1) 能打开裁判文书网的登录入口
  2) 能挑中真正的登录表单 iframe（不是扫码那个）
  3) 账号（手机号）/密码能自动填进去并被 Vue 接收
  4) 能定位到提交按钮
  5) 提交后能正确识别出「需要人工完成验证码 / 未确认结果」
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import autologin
from engine import Engine

FAKE_USER = "13800000000"
FAKE_PASS = "Dummy-Pass-123"


def main():
    out = os.path.join(tempfile.gettempdir(), "credit_shot_probe")
    eng = Engine(output_dir=out, browser="Edge", log=print)
    try:
        pw, browser, ctx, page = eng._open_browser()
    except Exception as exc:
        print("!! 浏览器启动失败：", exc)
        return

    # —— 把提交动作换成「只检查不点击」——
    state = {"submit_called": 0, "btn": None}

    def fake_submit(frame, log):
        state["submit_called"] += 1
        el = frame.query_selector(".login-button-container")
        state["btn"] = (el.inner_text() if el else None)
        print("  [打桩] 找到提交按钮：%r（不点击）" % state["btn"])
        return el is not None

    orig_submit = autologin._submit_wenshu
    autologin._submit_wenshu = fake_submit

    try:
        page.goto("https://wenshu.court.gov.cn/", timeout=60000,
                  wait_until="domcontentloaded")
        time.sleep(4)
        print("== 开始 try_login（真机，不提交）==")
        res = autologin.try_login(page, "wenshu", FAKE_USER, FAKE_PASS,
                                  print, None, None)
        print("\n== 结果 ==")
        print("  ok            :", res.ok)
        print("  filled        :", res.filled)
        print("  needs_captcha :", res.needs_captcha)
        print("  bad_credentials:", res.bad_credentials)
        print("  reason        :", res.reason)
        print("  提交被打桩次数:", state["submit_called"])

        # 顺便回读输入框，确认值真的进去了
        vals = page.evaluate("""()=>[]""")
        for f in page.frames:
            if "account.court.gov.cn" not in (f.url or ""):
                continue
            try:
                v = f.evaluate("""
                ()=>{const u=document.querySelector('input[name=username]');
                     const p=document.querySelector('input[type=password]');
                     return {u: u?u.value:'', p: p?('len='+String(p.value||'').length):''};}""")
            except Exception:
                continue
            if v and (v.get("u") or v.get("p")):
                print("  回读输入框    :", v)
    finally:
        autologin._submit_wenshu = orig_submit
        try:
            eng._close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
