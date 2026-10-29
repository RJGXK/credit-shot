# -*- coding: utf-8 -*-
"""GSXT 登录流程回归测试（用户反馈：点登录一直弹验证码，始终无法登录）。

用假页面 + 假时钟复现三种真实场景：

  A. 人工过完极验，**站点自己提交并整页跳回首页**
     -> 必须判定登录成功，而且**不能再点第二次登录**
        （旧代码在这里无条件再点一次 #btn_login，站点就再弹一次验证 -> 无限循环）

  B. 人工过完极验，但站点没提交（极验只做了校验）
     -> 观察 12 秒后**补点一次**登录，站点随即跳回首页 -> 判定成功

  C. 用户其实没过码（验证面板还在）
     -> 程序要再要一次人工，仍不行才报「需要人工」

跑法：python tools/check_gsxt_login.py
"""
from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import autologin  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ✔ " if ok else "  ✘ ") + name + (" — " + detail if detail else ""))
    if not ok:
        FAILED.append(name)


class _Handle:
    """模拟 Playwright 的 JSHandle。"""

    def __init__(self, value):
        self.value = value

    def json_value(self):
        return self.value


class _FakeGsxtPage:
    """gsxt 登录子站的假页面。"""

    def __init__(self, scenario="auto_jump"):
        self.scenario = scenario
        self.url = "https://shiming.gsxt.gov.cn/socialuser-use-login.html"
        self.text = "国家企业信用信息公示系统 用户登录 请输入手机号 请输入密码"
        self.geetest_visible = True      # 极验面板是否可见
        self.login_form = True           # 登录框还在不在
        self.submit_count = 0            # 点了几次「登录」
        self.manual_calls = 0            # 挂起等人工几次

    def _do_submit(self):
        """模拟站点对「点登录」的反应：在登录页上点登录 -> 又弹一次验证。"""
        self.submit_count += 1
        if self.scenario == "resubmit" and self.submit_count >= 2:
            # 极验只做校验、没提交；补点一次登录后站点才真正提交并跳回首页
            self.url = "https://www.gsxt.gov.cn/index.html"
        elif "shiming.gsxt.gov.cn" in self.url:
            self.geetest_visible = True

    # ---- Playwright 兼容接口 ----
    def title(self):
        return "国家企业信用信息公示系统"

    def wait_for_load_state(self, state, timeout=None):
        return None

    def wait_for_function(self, js, arg=None, timeout=None):
        if "btn_login" in js:
            self._do_submit()
            return _Handle(True)
        if "innerText" in js:
            return _Handle(self.text)
        return _Handle(True)

    def evaluate(self, js, arg=None):
        # ★ 白页探测的 JS 里同时含 document.body / hasKw / keyword，
        #   必须排在 "document.body" 分支之前
        if "hasKw" in js:
            # 白页探测：首页有搜索框不算白页；登录页有长文本也不算
            return {"len": len(self.text or ""), "hasKw":
                    self.url.startswith("https://www.gsxt.gov.cn")}
        if "ALREADY" in js:
            return "ALREADY"
        if "set('UserName'" in js:
            return "OK/OK"
        if "btn_login" in js:
            self._do_submit()
            return True
        if "document.body" in js:
            return self.text
        if "getElementById('UserName')" in js:
            return self.login_form
        if "geetest" in js:
            return self.geetest_visible
        if "getElementById('keyword')" in js:
            return self.url.startswith("https://www.gsxt.gov.cn")
        return True


class _Clock:
    """虚拟时钟：sleep 立刻推进时间，避免测试空等真实时间。"""

    def __init__(self):
        self.t = 1_700_000_000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


def _run(scenario, on_manual):
    """跑一次 _login_gsxt，返回 (结果, 页面, 日志)。"""
    clock = _Clock()
    page = _FakeGsxtPage(scenario)
    logs = []

    def wait_captcha(prompt):
        page.manual_calls += 1
        on_manual(page)

    with mock.patch.object(autologin, "time", clock):
        res = autologin.try_login(page, "gsxt", "13800138000", "pw",
                                  logs.append, wait_captcha, None)
    return res, page, logs


def case_a_auto_jump():
    """场景 A：人工过码 -> 站点自动提交并跳回首页。"""
    def on_manual(page):
        page.geetest_visible = False
        page.url = "https://www.gsxt.gov.cn/index.html"

    res, page, logs = _run("auto_jump", on_manual)
    check("A 登录成功", res.ok is True, res.reason)
    check("A 登录按钮只点了一次（不能再点，否则又弹验证）",
          page.submit_count == 1, "submit_count=%d" % page.submit_count)
    check("A 只挂起等人工一次", page.manual_calls == 1,
          "manual_calls=%d" % page.manual_calls)
    check("A 日志里没有「已再次提交登录」",
          not any("已再次提交登录" in m for m in logs),
          str(logs[-3:]))


def case_b_resubmit_once():
    """场景 B：极验只校验没提交 -> 补点一次登录后跳回。"""
    def on_manual(page):
        page.geetest_visible = False      # 面板消失，但站点不自动跳

    res, page, logs = _run("resubmit", on_manual)
    check("B 补点一次后登录成功", res.ok is True, res.reason)
    check("B 登录按钮共点了两次（初次 + 补点一次）",
          page.submit_count == 2, "submit_count=%d" % page.submit_count)
    check("B 日志里有「补点一次登录」",
          any("补点一次登录" in m for m in logs), str(logs[-3:]))


def case_c_captcha_still_there():
    """场景 C：用户没真过码 -> 再要一次人工，仍不行才报需要人工。"""
    def on_manual(page):
        pass                      # 什么都不做：验证面板还在

    res, page, logs = _run("still", on_manual)
    check("C 未确认登录成功", res.ok is False)
    check("C 需要人工处理", res.needs_captcha is True, res.reason)
    check("C 程序挂起了两次人工", page.manual_calls == 2,
          "manual_calls=%d" % page.manual_calls)


def case_d_blank_page_recover():
    """场景 D（用户实测）：人工过码后跳回首页被 WAF 拦成白页，刷新也没用。

    期望：程序给 8 秒恢复窗口 -> 用当前会话重新进入首页 -> 判定登录成功。
    """
    def on_manual(page):
        page.geetest_visible = False
        page.url = "https://www.gsxt.gov.cn/index.html"
        page.text = ""                    # 白页
        page.blank_mode = True

    # 在假页面上支持 blank_mode：白页时 hasKw 探测返回空；goto 重进后恢复
    def patch(page):
        def goto(url, wait_until=None, timeout=None):
            page.url = url
            page.blank_mode = False
            page.text = "国家企业信用信息公示系统首页"
            return True
        page.goto = goto

        orig = page.evaluate

        def evaluate(js, arg=None):
            if "hasKw" in js:
                if getattr(page, "blank_mode", False):
                    return {"len": len(page.text or ""), "hasKw": False}
                return {"len": len(page.text or ""), "hasKw":
                        page.url.startswith("https://www.gsxt.gov.cn")}
            return orig(js, arg)

        page.evaluate = evaluate

    clock = _Clock()
    page = _FakeGsxtPage("auto_jump")
    logs = []
    patch(page)

    def fake_chain(pp, site_key, log=print, **kw):
        # 模拟「经市场监管总局入口链重进」：落地即恢复首页
        pp.url = "https://www.gsxt.gov.cn/index.html"
        pp.blank_mode = False
        pp.text = "国家企业信用信息公示系统首页"
        log("  （假入口链：已恢复首页）")
        return {"ok": True, "page": pp}

    def wait_captcha(prompt):
        page.manual_calls += 1
        on_manual(page)

    with mock.patch.object(autologin, "time", clock), \
            mock.patch("core.nav.goto_via_landing", fake_chain):
        res = autologin.try_login(page, "gsxt", "13800138000", "pw",
                                  logs.append, wait_captcha, None)

    check("D 白页后登录成功", res.ok is True, res.reason)
    check("D 有「入口链重进」动作",
          any("入口链" in m for m in logs),
          str(logs[-3:]))
    check("D 白页恢复后登录按钮未被乱点", page.submit_count == 1,
          "submit_count=%d" % page.submit_count)


def main():
    case_a_auto_jump()
    case_b_resubmit_once()
    case_c_captcha_still_there()
    case_d_blank_page_recover()
    print()
    if FAILED:
        print("✘ 失败 %d 项：%s" % (len(FAILED), FAILED))
        sys.exit(1)
    print("✔ GSXT 登录流程全部通过")


if __name__ == "__main__":
    main()
