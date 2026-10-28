# -*- coding: utf-8 -*-
"""真机验证 wenshu 自动登录全链路（假密码，只看流程判定是否正确）。

关注点：
  1) 站点自跳转不再让整步失败；
  2) 登录 iframe 能被找到、密码框能定位；
  3) 账号密码能填进去并被站点接受（回读验证）；
  4) 提交后能判定出「需要人工完成验证码 / 账号密码不正确 / 登录成功」
     三者之一，而不是笼统的「未确认结果」；
  5) 打码服务回调被正确触发（若配了 Key）。
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
FAKE_USER = "13800000000"
FAKE_PASS = "Dummy-Pass-9"


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=print)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        print("\n== 打开首页 ==")
        nav.goto(page, "https://wenshu.court.gov.cn/", timeout_ms=60000, log=print)
        time.sleep(6)

        print("\n== 完整 try_login ==")
        calls = {"auto": 0, "manual": 0}

        def solve_captcha(frame):
            calls["auto"] += 1
            print("  [回调] 打码服务被调用")
            return False      # 模拟打码服务没搞定

        def wait_captcha(prompt):
            calls["manual"] += 1
            print("  [回调] 挂起等人工：%s" % prompt[:60])
            # 真机测试不真的等人工，直接返回
            return None

        res = autologin.try_login(page, "wenshu", FAKE_USER, FAKE_PASS,
                                  print, wait_captcha, solve_captcha)
        print("\n== 结果 ==")
        print("  ok            :", res.ok)
        print("  filled        :", res.filled)
        print("  needs_captcha :", res.needs_captcha)
        print("  bad_credentials:", res.bad_credentials)
        print("  reason        :", res.reason)
        print("  summary       :", res.summary)
        print("  打码回调次数  :", calls["auto"])
        print("  人工挂起次数  :", calls["manual"])

        try:
            page.screenshot(path=os.path.join(OUT, "wenshu_登录后.png"))
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
