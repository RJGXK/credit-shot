# -*- coding: utf-8 -*-
"""分组「全选」复选框真机验证（用户反馈：点击全选时不显示对勾）。

这是**浏览器行为**问题（HTML5 checkbox 的 canceled activation behavior），
必须用真浏览器点一次才算数，假页面测不出来。

跑法（需要系统 Python + 本机 Edge）：
    "C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe" tools/check_select_all.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from web.server import create_app, find_free_port

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

FAILED = []


def check(name, ok, detail=""):
    print(("  ✔ " if ok else "  ✘ ") + name + (" — " + detail if detail else ""))
    if not ok:
        FAILED.append(name)


def main() -> None:
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            if httpx.get(base + "/api/ping", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=EDGE, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.goto(base + "/", wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#checklist .site-block .site-head input", timeout=15000)
        page.wait_for_timeout(500)

        blocks = page.eval_on_selector_all(
            "#checklist .site-block",
            """els => els.map(e => ({
                 name: (e.querySelector('.site-name')||{}).textContent || '',
                 n: e.querySelectorAll('.step-row input').length }))""")
        print("=== 分组共 %d 个 ===" % len(blocks))

        for i, b in enumerate(blocks):
            sel = "#checklist .site-block:nth-of-type(%d) .site-head input" % (i + 1)
            rows = ("#checklist .site-block:nth-of-type(%d) .step-row input"
                    % (i + 1))
            name = b["name"][:14]

            def state():
                return page.evaluate(
                    """([sel, rows]) => {
                         const head = document.querySelector(sel);
                         const rs = [...document.querySelectorAll(rows)]
                                     .filter(c => !c.disabled);
                         return {head: head.checked, ind: head.indeterminate,
                                 n: rs.length,
                                 on: rs.filter(c => c.checked).length};
                       }""", [sel, rows])

            # --- 0) 初始状态：子项默认全勾 -> 组头也是勾上的 ---
            st0 = state()
            check("[%s] 初始状态组头与子项一致" % name,
                  st0["head"] is True and st0["on"] == st0["n"],
                  "head=%s on=%d/%d" % (st0["head"], st0["on"], st0["n"]))

            # --- 1) 已全勾时点组头 -> 全部取消（组头也不能残留对勾）---
            page.click(sel)
            page.wait_for_timeout(120)
            st1 = state()
            check("[%s] 已全勾时点一下 -> 全部取消且组头不显示对勾" % name,
                  st1["head"] is False and st1["on"] == 0 and st1["ind"] is False,
                  "head=%s ind=%s on=%d" % (st1["head"], st1["ind"], st1["on"]))

            # --- 2) 再点一次 -> 全勾，**组头必须显示对勾**（用户反馈的 bug）---
            page.click(sel)
            page.wait_for_timeout(120)
            st2 = state()
            check("[%s] 点全选后组头显示对勾" % name,
                  st2["head"] is True and st2["ind"] is False,
                  "head=%s ind=%s" % (st2["head"], st2["ind"]))
            check("[%s] 点全选后子项全勾" % name,
                  st2["n"] > 0 and st2["on"] == st2["n"],
                  "%d/%d" % (st2["on"], st2["n"]))

            # --- 3) 半选状态：只勾一个子项 -> 组头半选 -> 点组头 -> 全勾 ---
            page.evaluate(
                """(rows) => {
                     const rs = [...document.querySelectorAll(rows)]
                                 .filter(c => !c.disabled);
                     rs.forEach(c => { c.checked = false; });
                     if (rs[0]) { rs[0].checked = true;
                                  rs[0].dispatchEvent(new Event('change',{bubbles:true})); }
                   }""", rows)
            page.wait_for_timeout(120)
            ind = page.evaluate("(sel)=>document.querySelector(sel).indeterminate", sel)
            st4 = state()
            if st4["n"] > 1:
                check("[%s] 单勾子项后组头为半选" % name, ind is True,
                      "indeterminate=%s" % ind)
                page.click(sel)
                page.wait_for_timeout(120)
                st4 = state()
                check("[%s] 半选后点组头变全勾且显示对勾" % name,
                      st4["head"] is True and st4["ind"] is False
                      and st4["on"] == st4["n"],
                      "head=%s ind=%s on=%d/%d" % (st4["head"], st4["ind"],
                                                  st4["on"], st4["n"]))
            else:
                # 只有一个可用子项时不存在「半选」态：勾上它组头就该是对勾
                check("[%s] 单条目分组勾上即全勾" % name,
                      st4["head"] is True and st4["on"] == 1,
                      "head=%s on=%d/1" % (st4["head"], st4["on"]))

            # 复原：全部取消
            page.evaluate(
                """(rows) => {
                     document.querySelectorAll(rows).forEach(c => { c.checked = false; });
                   }""", rows)
            page.evaluate("() => window.refreshCounts && window.refreshCounts()")

        browser.close()

    print()
    if FAILED:
        print("✘ 失败 %d 项：%s" % (len(FAILED), FAILED))
        sys.exit(1)
    print("✔ 全选框全部通过")


if __name__ == "__main__":
    main()
