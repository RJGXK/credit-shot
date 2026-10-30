# -*- coding: utf-8 -*-
"""实测软件 Profile 的真实登录态，及「登录态下查询是否被放行」。

对照结论：同一 IP，用户自己的浏览器（登录态）能查；软件浏览器（匿名）
点查询被静默吞。本探针验证：软件 Profile 是否已登录 / 登录态下查询是否放行。
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


def login_state(page) -> dict:
    try:
        return page.evaluate("""()=>{
          const b=(document.body&&document.body.innerText)||'';
          return {logged:/退出登录|个人中心|欢迎您|安全退出/.test(b),
                  hasLoginBtn:/^登录$/.test(b.replace(/\\s+/g,''))===false
                             && /登录/.test(b),
                  snippet:b.replace(/\\s+/g,' ').slice(0,150)};
        }""")
    except Exception as e:
        return {"err": str(e)[:60]}


def main() -> int:
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()
    try:
        log("=== 1) 入口链进首页 ===")
        res = nav.goto_via_landing(page, "gsxt", log=log, timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            log("入口失败：%s" % res.get("reason"))
            return 1
        log("=== 2) 软件 Profile 真实登录态 ===")
        st = login_state(landed)
        log("已登录=%s | 正文：%s" % (st.get("logged"), st.get("snippet", "")[:110]))

        log("=== 3) 当前会话查询测试 ===")
        if not fill_controlled(landed, "() => document.getElementById('keyword')",
                               COMPANY):
            log("填词失败")
            return 1
        time.sleep(0.8)
        try:
            loc = landed.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            log("点击：TRUSTED_CLICK")
        except Exception as exc:
            log("点击失败:%s" % str(exc)[:50])
            return 1
        deadline = time.time() + 14
        verdict = "✘ 无反应"
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
            if r.get("listing"):
                verdict = "✔ 跳到结果页"
                break
            if r.get("vis"):
                verdict = "✔ 极验弹出"
                break
            time.sleep(2)
        log("查询判定：%s" % verdict)
        log("")
        log("=== 结论 ===")
        log("软件 Profile 已登录=%s；查询=%s" % (st.get("logged"), verdict))
        if not st.get("logged") and verdict.startswith("✘"):
            log("→ 匿名被吞 + 未登录：需要走实名登录通道（用户浏览器正是登录态）")
        return 0
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
