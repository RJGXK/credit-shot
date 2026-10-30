# -*- coding: utf-8 -*-
"""A/B 对照实验：锁定「点查询被吞」的真变量。

变量：① 查询词（北京百度网讯科技 vs 中瑞盛世）；② 填词方式（setter 灌值 vs insertText）。
两个探针在其他条件完全一致下各跑一次，看谁被吞。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402
from core.page import fill_controlled     # noqa: E402

SETTER_JS = """
(name)=>{
  const el=document.getElementById('keyword');
  if(!el) return 'NO_INPUT';
  const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
  el.focus(); set.call(el,name);
  el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}));
  return el.value===name ? 'OK' : 'VALUE_FAIL';
}
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def one_round(bs, company: str, fill_mode: str) -> str:
    pw, browser, ctx, page = bs.open()
    try:
        res = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                   timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            return "入口失败"
        try:
            landed.wait_for_function("()=>document.readyState==='complete'",
                                     timeout=15000)
        except Exception:
            pass
        if fill_mode == "setter":
            r = landed.evaluate(SETTER_JS, company)
            if r != "OK":
                return "填词失败(%s)" % r
        else:
            if not fill_controlled(landed,
                                   "() => document.getElementById('keyword')",
                                   company):
                return "填词失败"
        time.sleep(0.8)
        try:
            loc = landed.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
        except Exception as exc:
            return "点击失败:%s" % str(exc)[:40]
        deadline = time.time() + 14
        while time.time() < deadline:
            try:
                r = landed.evaluate("""()=>{
                  const sel='.geetest_panel_box,.geetest_window,.geetest_holder';
                  const e=document.querySelector(sel);
                  let vis=false;
                  if(e){const b=e.getBoundingClientRect();
                        const s=getComputedStyle(e);
                        vis=b.width>50&&b.height>40
                           &&s.display!=='none'&&s.visibility!=='hidden';}
                  return {listing:/corp-query-search/.test(location.href), vis:vis};
                }""")
            except Exception:
                r = {}
            if r.get("listing") or r.get("vis"):
                return "✔ 有反应"
            time.sleep(2)
        return "✘ 被吞"
    finally:
        pass


def main() -> int:
    cases = [
        ("中瑞盛世", "setter", "中瑞盛世（北京）建筑有限公司"),
        ("中瑞盛世", "insert", "中瑞盛世（北京）建筑有限公司"),
        ("百度", "setter", "北京百度网讯科技有限公司"),
    ]
    results = []
    for idx, (tag, mode, comp) in enumerate(cases):
        log("--- case %d: %s / %s ---" % (idx + 1, tag, mode))
        bs = BrowserSession("Edge", log=lambda *a, **k: None, timeout=30)
        r = one_round(bs, comp, mode)
        log("结果：%s" % r)
        results.append((tag, mode, r))
        try:
            bs.close()
        except Exception:
            pass
        time.sleep(3.0)
    log("")
    log("=== 汇总 ===")
    for tag, mode, r in results:
        log("  %s/%s → %s" % (tag, mode, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
