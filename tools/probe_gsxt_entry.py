# -*- coding: utf-8 -*-
"""临时探针：验证 gsxt 的「搜索引擎进站 + 点查询」链路是否真能走通。

    python tools/probe_gsxt_entry.py

只做：
  1) 走 nav.goto_via_landing("gsxt")（现在是 Bing 搜索 → 点结果）
  2) 打印落地 URL / 是否有 #keyword / 是否有拒绝页文案
  3) 填企业名 → 真实点击【查询】→ 8 秒内看是否跳转 / 弹极验 / 被拒
不做：登录、选企业、截图。跑完自己关浏览器。
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    company = "北京百度网讯科技有限公司"
    bs = BrowserSession("Edge", log=log, timeout=30)
    bs.open()
    page = None
    for p in bs.ctx.pages:
        if "about:blank" in (p.url or "") or not (p.url or ""):
            page = p
            break
    if page is None:
        page = bs.ctx.pages[0] if bs.ctx.pages else bs.ctx.new_page()

    log("=== 1) 走入口链（Bing → 点结果）===")
    res = nav.goto_via_landing(page, "gsxt", log=log)
    log("入口结果：ok=%s via=%s reason=%s" % (res.get("ok"), res.get("via"),
                                             res.get("reason")))
    # 入口可能开新标签页：后续操作必须打在真正落地的那一页上
    page = res.get("page") or page

    def state() -> dict:
        try:
            return page.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              const el=document.getElementById('keyword');
              const r=el?el.getBoundingClientRect():null;
              return {url:location.href, title:document.title||'',
                      kw: !!(r&&r.width>0&&r.height>0),
                      blocked: /当前IP请求异常|可疑的攻击行为|更换IP地址|400 Bad Request/.test(b),
                      len:b.length,
                      head:b.replace(/\\s+/g,' ').slice(0,120)};
            }""")
        except Exception as exc:
            return {"err": str(exc)[:80]}

    st = state()
    log("落地：url=%s" % str(st.get("url"))[:90])
    log("      title=%s len=%s 有搜索框=%s 被拒=%s"
        % (st.get("title"), st.get("len"), st.get("kw"), st.get("blocked")))
    if st.get("head"):
        log("      正文：%s" % st["head"])

    log("=== 2) 填企业名 + 真实点击【查询】===")
    try:
        page.wait_for_function("()=>document.readyState==='complete'", timeout=15000)
    except Exception:
        pass
    ok_fill = page.evaluate("""(name)=>{
      const el=document.getElementById('keyword');
      if(!el) return 'NO_INPUT';
      const proto=HTMLInputElement.prototype;
      const set=Object.getOwnPropertyDescriptor(proto,'value').set;
      el.focus(); set.call(el,name);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return el.value===name ? 'OK' : ('VALUE:'+el.value);
    }""", company)
    log("填词：%s" % ok_fill)

    clicked = "NONE"
    try:
        loc = page.locator("#btn_query").first
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=5000)
        clicked = "TRUSTED_CLICK"
    except Exception as exc:
        clicked = "FAIL:%s" % str(exc).splitlines()[0][:60]
    log("点击：%s" % clicked)

    deadline = time.time() + 10
    reacted = ""
    while time.time() < deadline:
        try:
            r = page.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              const gt=document.querySelector('.geetest_holder,.geetest_panel,#popup-captcha');
              const gtb=gt?gt.getBoundingClientRect():null;
              return {url:location.href,
                      geetest: !!(gtb&&gtb.width>40&&gtb.height>40),
                      blocked: /当前IP请求异常|可疑的攻击行为|400 Bad Request/.test(b),
                      listing: /corp-query-search/.test(location.href)};
            }""")
        except Exception:
            r = {}
        if r.get("listing"):
            reacted = "跳到结果页：%s" % str(r.get("url"))[:80]
            break
        if r.get("geetest"):
            reacted = "弹出极验（正常，需人工过验证）"
            break
        if r.get("blocked"):
            reacted = "被拒（拒绝页/400）"
            break
        time.sleep(1.0)
    log("查询反应：%s" % (reacted or "10 秒内没有任何反应"))

    log("=== 结束（3 秒后关闭浏览器）===")
    time.sleep(3)
    try:
        bs.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
