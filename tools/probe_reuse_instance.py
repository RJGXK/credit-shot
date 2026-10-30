# -*- coding: utf-8 -*-
"""复用旧 Edge 实例场景探针：复现软件真实运行环境（不关上次留下的浏览器）。

背景：v2.2.0~v2.2.8 的「点了查询没反应 / 400 票据判废」都发生在
**复用旧实例**时；探针（新进程）却全程正常。本探针故意复用已开的
Edge 实例（与软件行为一致），逐步打印每一步，定位差异。

用法：
    ① 先随便跑一次软件或 probe_gsxt_entry.py 留下一个 Edge 实例；
    ② 再跑本脚本：python tools/probe_reuse_instance.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    company = "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()
    try:
        log("=== 复用实例探针：标签页数=%d ===" % len(ctx.pages))
        for i, p in enumerate(ctx.pages):
            try:
                log("  tab[%d] url=%s" % (i, (p.url or "")[:80]))
            except Exception as e:
                log("  tab[%d] 不可读: %s" % (i, e))

        log("=== 1) 入口链（与软件同款 goto_via_landing）===")
        res = nav.goto_via_landing(page, "gsxt", log=log, timeout_ms=45000)
        landed = res.get("page") or page
        log("入口结果：ok=%s via=%s" % (res.get("ok"), res.get("via")))
        try:
            st = nav.nav_state(landed)
            log("落地：url=%s len=%s blank=%s"
                % (str(st.get("url"))[:70], st.get("len"), st.get("blank")))
        except Exception as e:
            log("落地读取失败：%s" % e)

        log("=== 2) 慢速填词 + 真实点击查询 ===")
        from core.page import fill_controlled
        ok_fill = fill_controlled(landed,
                                  "() => document.getElementById('keyword')",
                                  company)
        log("填词：%s" % ("OK" if ok_fill else "FAIL"))
        time.sleep(0.8)
        clicked = "NONE"
        try:
            loc = landed.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            clicked = "TRUSTED_CLICK"
        except Exception as exc:
            clicked = "FAIL:%s" % str(exc).splitlines()[0][:60]
        log("点击：%s" % clicked)

        log("=== 3) 点查询后反应时间线（每 2 秒，最多 20 秒）===")
        deadline = time.time() + 20
        reacted = ""
        while time.time() < deadline:
            try:
                r = landed.evaluate("""()=>{
                  const b=(document.body&&document.body.innerText)||'';
                  return {url:location.href,
                          blocked:/当前IP请求异常|可疑的攻击行为|400 Bad Request/.test(b),
                          listing:/corp-query-search/.test(location.href),
                          blen:b.length};
                }""")
            except Exception:
                r = {}
            if r.get("listing"):
                reacted = "跳到结果页"
                break
            if r.get("blocked"):
                reacted = "被拒（IP风控/400）正文=%s" % r.get("blen")
                break
            time.sleep(2)
        log("查询反应：%s" % (reacted or "20 秒内无跳转/无明确拒绝页"))

        log("=== 4) Cookie 票据快照 ===")
        try:
            cks = landed.context.cookies(urls=["https://www.gsxt.gov.cn"])
            names = sorted({str(c.get("name") or "") for c in cks})
            log("票据：%s" % ("、".join(names) if names else "（空）"))
        except Exception as e:
            log("Cookie 读取失败：%s" % e)
        return 0
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
