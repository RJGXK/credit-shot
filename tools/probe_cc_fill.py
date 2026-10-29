# -*- coding: utf-8 -*-
"""探针：信用中国验证码到底卡在哪一步？

三个嫌疑点，逐个实测：
  A. 填入有没有真的写进输入框 —— **读回 input.value** 对比填进去的文本。
     如果读回来的是上一轮的值，那就是用户说的「总是输入识别到的上一个验证码」。
  B. 打码服务识别得准不准 —— 人工肉眼读图，和识别结果对比。
  C. 弹层里到底有几个输入框，_fill_captcha_input 选中的是哪一个。

用法：python tools/probe_cc_fill.py [公司名]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver           # noqa: E402
from auth.credentials import load_captcha_key    # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

INPUTS_JS = """
()=>{
  const pop=document.querySelector('.vcodepop');
  const scope = pop || document;
  const all=[...scope.querySelectorAll('input:not([type=hidden]),textarea')];
  const box=document.querySelector('.vcodeimgbox');
  return {
    popFound: !!pop,
    popDisplay: pop?getComputedStyle(pop).display:'',
    inputs: all.map(i=>({tag:i.tagName, id:i.id||'', name:i.name||'',
                          type:i.type||'', ph:i.placeholder||'',
                          maxlen:i.maxLength, value:i.value||'',
                          visible:(()=>{const b=i.getBoundingClientRect();
                                        return b.width>0&&b.height>0;})()})),
    bodyInputs: [...document.querySelectorAll('input:not([type=hidden])')].map(i=>({
                  id:i.id||'', name:i.name||'', ph:i.placeholder||'',
                  value:i.value||'', visible:(()=>{const b=i.getBoundingClientRect();
                                        return b.width>0&&b.height>0;})()})),
    boxText: box?(box.innerText||'').replace(/\\s+/g,' ').slice(0,80):'',
  };
}
"""


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    key = load_captcha_key()
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

        import json
        print("\n===== 弹层 DOM =====")
        print(json.dumps(page.evaluate(INPUTS_JS), ensure_ascii=False, indent=2)[:2500])

        solver = CaptchaSolver(key, "cn", print)
        scope = page.query_selector(".vcodepop")

        # ---- A. 填入后立刻读回 ----
        probe_text = "AB7CD"
        print("\n===== A. 填入测试（填 %s，读回）=====" % probe_text)
        ok = solver._fill_captcha_input(page, ".vcodepop", probe_text)
        print("  _fill_captcha_input 返回：%s" % ok)
        got = page.evaluate(
            """()=>{
              const pop=document.querySelector('.vcodepop');
              const scope=pop||document;
              const all=[...scope.querySelectorAll('input:not([type=hidden]),textarea')];
              return all.map(i=>({id:i.id||'', name:i.name||'', ph:i.placeholder||'',
                                  value:i.value||''}));
            }""")
        print("  填入后各输入框的值：%s" % json.dumps(got, ensure_ascii=False))
        hit = [g for g in got if g["value"] == probe_text]
        print("  → 找到写入目标值的框：%s" % (hit if hit else "没有！值没写进去"))

        # ---- B. 识别准确度 ----
        print("\n===== B. 打码服务识别 =====")
        for i in range(2):
            raw, how, meta = solver._capture_captcha(page, "#vcodeimg", scope, ".vcodepop")
            if not raw:
                print("  第%d张：没取到图" % (i + 1))
                continue
            fn = os.path.join(OUT, "probe_fill_%d.png" % (i + 1))
            open(fn, "wb").write(raw)
            txt = ""
            try:
                from core.captcha import preprocess_captcha
                txt = solver.client().solve_image_to_text(preprocess_captcha(raw))
            except Exception as exc:
                txt = "ERR:%s" % exc
            print("  第%d张 -> %s  识别为 %r  （图：%s）"
                  % (i + 1, how, txt, fn))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
