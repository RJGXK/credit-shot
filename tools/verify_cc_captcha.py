# -*- coding: utf-8 -*-
"""真机验证：信用中国验证码「总是输入识别到的上一个验证码」是否修好了。

跑完整闭环：打开信用中国 -> 填主体 -> 触发验证码弹层 ->
走 core.captcha.solve_image_captcha（含打码服务）-> 判定是否通过。

重点看三件事：
  1. 取到的图是不是**真图**（naturalWidth > 0，破图会被挡掉）；
  2. 每一轮提交的图**指纹是否都不同**（相同就说明还在提交上一张）；
  3. 识别期间站点换图时，本次结果会不会被作废。

用法：
  "C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe" tools/verify_cc_captcha.py [公司名]
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver, image_fingerprint  # noqa: E402
from auth.credentials import load_captcha_key    # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

STATE_JS = """
()=>{
  const all=[...document.querySelectorAll('#vcodeimg')];
  const vis=all.filter(i=>{
    const b=i.getBoundingClientRect(); const st=getComputedStyle(i);
    return st.display!=='none'&&st.visibility!=='hidden'&&b.width>0&&b.height>0;});
  const pick=vis[0]||all[0]||null;
  return {count:all.length, visible:vis.length,
          nat: pick?((pick.naturalWidth||0)+'x'+(pick.naturalHeight||0)):'none',
          complete: pick?!!pick.complete:false,
          src: pick?((pick.currentSrc||pick.src||'').slice(-60)):''};
}
"""


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    key = load_captcha_key()
    print("打码服务 API Key：%s" % ("已配置（长度 %d）" % len(key) if key else "未配置"))
    if not key:
        print("⚠ 没有 API Key，自动识别跑不了；只做取图验证。")
        return

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
            shown = page.evaluate("()=>{const p=document.querySelector('.vcodepop');"
                                  "return !!(p&&getComputedStyle(p).display!=='none');}")
            if shown:
                break
            time.sleep(1.0)
        time.sleep(2)

        print("\n-- 弹层状态 --")
        print(" ", page.evaluate(STATE_JS))

        # 包一层，把每轮取到的图存盘 + 记指纹
        solver = CaptchaSolver(key, "cn", print)
        real_capture = solver._capture_captcha
        rounds = {"n": 0, "fps": []}

        def spy(page_, sel, scope, scope_selector=""):
            raw, how, meta = real_capture(page_, sel, scope, scope_selector)
            rounds["n"] += 1
            fp = image_fingerprint(raw or b"")
            rounds["fps"].append(fp)
            if raw:
                open(os.path.join(OUT, "verify_cc_%d.png" % rounds["n"]), "wb").write(raw)
            print("  [第%d轮] 取图 how=%s size=%s 指纹=%s src=%s"
                  % (rounds["n"], how, len(raw or b""), fp,
                     (meta or {}).get("src", "")[-40:]))
            return raw, how, meta

        solver._capture_captcha = spy

        def vcode_ok():
            st = page.evaluate(
                "()=>({v:(document.cookie||'').includes('vcode=1'),"
                "pop:!!(document.querySelector('.vcodepop')"
                "&&getComputedStyle(document.querySelector('.vcodepop')).display!=='none')})")
            return bool(st and (st.get("v") or not st.get("pop")))

        print("\n-- 开始自动识别 --")
        ok = solver.solve_image_captcha(
            page, img_selector="#vcodeimg", scope_selector=".vcodepop",
            confirm_selectors=(".vcodepop a.confirm", ".vcodepop .confirm"),
            success_check=vcode_ok, tries=5)

        print("\n===== 结果 =====")
        print("  自动通过：%s" % ok)
        print("  取图轮数：%d，指纹：%s" % (rounds["n"], rounds["fps"]))
        if len(rounds["fps"]) > 1:
            same = len(set(rounds["fps"])) != len(rounds["fps"])
            print("  是否出现重复指纹（=提交了上一张图）：%s" % ("是（有问题）" if same else "否"))
        print("  截图目录：%s" % OUT)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
