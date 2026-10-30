# -*- coding: utf-8 -*-
"""实测用户手动套路：查询被吞后「返回上一级 → 重新点进 → 刷新」能否复活。

用户原话：返回上一级，然后再点进入、刷新试试。
流程：
  round1: 入口 → 填词 → 点查询（预期被吞）
  恢复:   go_back() 回到搜索引擎 → 重新点结果进 gsxt → reload 刷新
  round2: 再填词 → 再点查询 → 判定
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402
from core.page import fill_controlled     # noqa: E402

COMPANY = "中瑞盛世（北京）建筑有限公司"


def log(msg: str) -> None:
    print(msg, flush=True)


def try_query(page, tag: str) -> str:
    # 等搜索框真正可见（刷新/重进后渲染要时间）
    try:
        page.wait_for_selector("#keyword", state="visible", timeout=20000)
    except Exception:
        return "搜索框未出现（页面没渲染出来）"
    if not fill_controlled(page, "() => document.getElementById('keyword')",
                           COMPANY):
        return "填词失败"
    time.sleep(0.8)
    try:
        loc = page.locator("#btn_query").first
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=5000)
        log("  [%s] 点击：TRUSTED_CLICK" % tag)
    except Exception as exc:
        return "点击失败:%s" % str(exc)[:40]
    deadline = time.time() + 14
    while time.time() < deadline:
        try:
            r = page.evaluate("""()=>{
              const sel='.geetest_panel_box,.geetest_window,.geetest_holder';
              const e=document.querySelector(sel);
              let vis=false;
              if(e){const b=e.getBoundingClientRect();
                    vis=b.width>50&&b.height>40;}
              return {listing:/corp-query-search/.test(location.href), vis:vis};
            }""")
        except Exception:
            r = {}
        if r.get("listing"):
            return "✔ 跳到结果页"
        if r.get("vis"):
            return "✔ 极验弹出"
        time.sleep(2)
    return "✘ 被吞"


def main() -> int:
    bs = BrowserSession("Edge", log=lambda *a, **k: None, timeout=30)
    pw, browser, ctx, page = bs.open()
    try:
        log("=== round1：入口 → 查询 ===")
        res = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                   timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            log("入口失败")
            return 1
        r1 = try_query(landed, "round1")
        log("round1：%s" % r1)
        if not r1.startswith("✘"):
            log("round1 已通，无需恢复")
            return 0

        log("=== 恢复：返回上一级 ===")
        try:
            landed.go_back(wait_until="domcontentloaded", timeout=20000)
            log("go_back 完成，当前：%s" % (landed.url or "")[:70])
        except Exception as exc:
            log("go_back 失败：%s" % str(exc)[:60])

        log("=== 恢复：重新点进 gsxt（当前页若是搜索页就再点结果）===")
        time.sleep(2)
        try:
            cur_host = str(landed.evaluate("()=>location.host") or "")
        except Exception:
            cur_host = ""
        if "bing.com" in cur_host or "baidu.com" in cur_host:
            landed.reload(wait_until="domcontentloaded")
            time.sleep(3)
            res2 = nav.goto_via_landing(landed, "gsxt",
                                        log=lambda *a, **k: None,
                                        timeout_ms=45000)
            landed = res2.get("page") or landed
            log("重新进入：%s ok=%s" % (str(landed.url)[:60], res2.get("ok")))
        elif "gsxt.gov.cn" in cur_host:
            # 已经回到 gsxt 域：直接刷新（用户说「刷新试试」）
            landed.reload(wait_until="domcontentloaded")
            time.sleep(5)
            landed.reload(wait_until="domcontentloaded")
            log("已在 gsxt 域，刷新两次")
        else:
            # 未知位置：整条入口链重走
            res2 = nav.goto_via_landing(landed, "gsxt",
                                        log=lambda *a, **k: None,
                                        timeout_ms=45000)
            landed = res2.get("page") or landed
            log("重走入口链 ok=%s" % res2.get("ok"))

        log("=== round2：恢复后查询 ===")
        time.sleep(3)
        try:
            landed.reload(wait_until="domcontentloaded")
            time.sleep(4)
            log("最终刷新完成：%s" % (landed.url or "")[:70])
        except Exception:
            pass
        r2 = try_query(landed, "round2")
        log("round2：%s" % r2)
        log("")
        log("=== 结论 ===")
        log("round1=%s | 恢复(返回→重进→刷新)后 round2=%s" % (r1, r2))
        return 0
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
