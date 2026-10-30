# -*- coding: utf-8 -*-
"""验证自救路径：清票据 → 重启进程 → 再查（与 v2.2.9 的 _resolve_ip_block 同序）。

验证目标：
  A. 只清票据（Storage.clearDataForOrigin）后能否恢复？
  B. 清票据 + 重启浏览器进程后能否恢复？
结论会打印在最末尾。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402
from core.page import fill_controlled     # noqa: E402

TICKET_ORIGINS = ["https://www.gsxt.gov.cn", "https://gsxt.gov.cn",
                  "https://shiming.gsxt.gov.cn", "http://www.gsxt.gov.cn"]


def log(msg: str) -> None:
    print(msg, flush=True)


def tickets(page):
    try:
        cks = page.context.cookies(urls=["https://www.gsxt.gov.cn"])
        return sorted({str(c.get("name") or "") for c in cks}
                      & {"__jsluid_s", "__jsl_clearance_s", "SECTOKEN",
                         "JSESSIONID"})
    except Exception:
        return []


def clear_tickets(page) -> bool:
    ok = False
    try:
        cdp = page.context.new_cdp_session(page)
        for origin in TICKET_ORIGINS:
            try:
                cdp.send("Storage.clearDataForOrigin",
                         {"origin": origin,
                          "storageTypes": "cookies,local_storage,session_storage"})
                ok = True
            except Exception:
                continue
        try:
            cdp.detach()
        except Exception:
            pass
    except Exception:
        pass
    return ok


def attempt_query(bs, tag: str) -> str:
    """走一次完整链：入口 → 填词 → 点查询 → 判定反应。"""
    pw, browser, ctx, page = bs.open()
    try:
        res = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                   timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            return "入口失败"
        if not fill_controlled(landed,
                               "() => document.getElementById('keyword')",
                               "中瑞盛世（北京）建筑有限公司"):
            return "填词失败"
        time.sleep(0.8)
        try:
            loc = landed.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
        except Exception:
            return "点击失败"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = landed.evaluate("""()=>{
                  return {listing:/corp-query-search/.test(location.href),
                          gt:!!(document.querySelector(
                            '.geetest_panel_box,.geetest_window,.geetest_holder')
                            && (()=>{const e=document.querySelector(
                              '.geetest_panel_box,.geetest_window,.geetest_holder');
                              const b=e.getBoundingClientRect();
                              return b.width>50&&b.height>40;})())};
                }""")
            except Exception:
                r = {}
            if r.get("listing") or r.get("gt"):
                return "✔ 有反应（结果页/极验弹出）"
            time.sleep(2)
        return "✘ 无反应（被吞）"
    finally:
        pass


def main() -> int:
    company_tag = "验证自救路径"
    log("=== 实验 A：只清票据（不重启进程）===")
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()
    log("清理前票据：%s" % ("、".join(tickets(page)) or "（无）"))
    cleared = clear_tickets(page)
    log("CDP 清理执行：%s" % ("成功" if cleared else "失败"))
    log("清理后票据：%s" % ("、".join(tickets(page)) or "（已清空）"))
    r1 = attempt_query(bs, "A")
    log("实验 A 结果：%s" % r1)
    try:
        bs.close()
    except Exception:
        pass

    log("")
    log("=== 实验 B：清票据 + 重启浏览器进程 ===")
    bs2 = BrowserSession("Edge", log=log, timeout=30)
    pw2, b2, ctx2, pg2 = bs2.open()
    clear_tickets(pg2)
    try:
        bs2.close()
    except Exception:
        pass
    time.sleep(2.0)
    bs3 = BrowserSession("Edge", log=log, timeout=30)
    r2 = attempt_query(bs3, "B")
    log("实验 B 结果：%s" % r2)
    try:
        bs3.close()
    except Exception:
        pass
    log("")
    log("=== 结论 ===")
    log("A（只清票据）：%s" % r1)
    log("B（清票据+重启进程）：%s" % r2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
