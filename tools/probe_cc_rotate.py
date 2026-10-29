# -*- coding: utf-8 -*-
"""探针7：站点判错后，**验证码图会不会被站点换掉**？

这决定了能不能「同一张图试多个候选答案」：
  · 站点判错后**不换图** -> 我们可以拿同一张图换几种预处理/题型各试一次，
    直到有一个被接受（总有一轮能蒙对）；
  · 站点判错后**换图** -> 每试错一次就得重新取图重新识别，
    只能靠提高单次识别率。

做法：先故意填一个错的码提交，再看 img 的 src 变没变。

用法：python tools/probe_cc_rotate.py [公司名]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver           # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"


def snap(page):
    return page.evaluate(
        """()=>{const i=document.querySelector('#vcodeimg');
             const e=document.querySelector('.vcodepop .errortip');
             return {src:(i&&(i.currentSrc||i.src||''))||'',
                     nat:i?((i.naturalWidth||0)+'x'+(i.naturalHeight||0)):'',
                     err:e?((e.innerText||'').trim()):''};}""")


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称')"
                  " && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn');"
                      " if(b) b.click();}")
        deadline = time.time() + 25
        while time.time() < deadline:
            if page.evaluate("()=>{const p=document.querySelector('.vcodepop');"
                             "return !!(p&&getComputedStyle(p).display!=='none');}"):
                break
            time.sleep(1.0)
        time.sleep(3)

        solver = CaptchaSolver("", "cn", print)
        scope = page.query_selector(".vcodepop")

        s0 = snap(page)
        print("\n提交前：src=%s nat=%s" % (s0["src"][-26:], s0["nat"]))

        print("\n>>> 故意填一个错的码（ZZZZZ）并提交")
        solver._fill_captcha_input(page, ".vcodepop", "ZZZZZ")
        page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm');"
                      " if(b) b.click();}")
        time.sleep(3)
        s1 = snap(page)
        print("提交后：src=%s nat=%s 错误提示=%r"
              % (s1["src"][-26:], s1["nat"], s1["err"]))
        if s1["src"] == s0["src"]:
            print("→ ★ 站点判错后**没有换图**（src 没变）：同一张图可以试多个候选答案")
        else:
            print("→ 站点判错后**换了图**（src 变了）：只能靠单次识别率")

        print("\n>>> 再故意填一个错的码（YYYYY），看还能不能连着试")
        solver._fill_captcha_input(page, ".vcodepop", "YYYYY")
        page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm');"
                      " if(b) b.click();}")
        time.sleep(3)
        s2 = snap(page)
        print("再提交后：src=%s 错误提示=%r" % (s2["src"][-26:], s2["err"]))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
