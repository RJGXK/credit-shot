# -*- coding: utf-8 -*-
"""快速诊断：首页「登录」入口找得到吗？真实点击能打开登录页吗？"""
from __future__ import annotations

import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()
    try:
        log("=== 1) 入口进首页 ===")
        res = nav.goto_via_landing(page, "gsxt", log=log, timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            log("入口失败：%s" % res.get("reason"))
            return 1
        time.sleep(1.5)
        log("=== 2) 首页「登录」候选扫描 ===")
        r = landed.evaluate("""()=>{
          const norm=s=>(s||'').replace(/\\s+/g,'').trim();
          return [...document.querySelectorAll('a,span,div,li,button')]
            .filter(e=>{
              const t=norm(e.innerText||e.textContent||'');
              if(t!=='登录') return false;
              const b=e.getBoundingClientRect();
              return b.width>0&&b.height>0;})
            .map(e=>{
              const b=e.getBoundingClientRect();
              return {tag:e.tagName, cls:(e.className||'').toString().slice(0,40),
                      x:Math.round(b.left), y:Math.round(b.top),
                      w:Math.round(b.width), h:Math.round(b.height),
                      href:(e.href||'').slice(0,60)};});
        }""")
        log("「登录」候选数：%s" % json.dumps(r, ensure_ascii=False))
        if not r:
            log("⚠ 首页上没有可见的「登录」二字（可能页面结构变化或被顶栏收起）")
            body = landed.evaluate(
                "()=>(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)")
            log("正文：%s" % body)
            return 1
        log("=== 3) 真实鼠标点第一个候选 ===")
        c = r[0]
        try:
            landed.mouse.click(c["x"] + c["w"] // 2, c["y"] + c["h"] // 2)
            log("已点击 (%d,%d)" % (c["x"] + c["w"] // 2, c["y"] + c["h"] // 2))
        except Exception as exc:
            log("点击失败：%s" % str(exc)[:60])
            return 1
        log("=== 4) 等 15 秒看 #UserName 是否出现 ===")
        deadline = time.time() + 15
        hit = False
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                pages = list(page.context.pages)
            except Exception:
                pages = []
            for p in pages:
                try:
                    if p.evaluate("()=>!!document.getElementById('UserName')"):
                        log("✔ 登录页已打开：%s" % (p.url or "")[:70])
                        hit = True
                        break
                except Exception:
                    continue
            if hit:
                break
            try:
                log("  …等待中 url=%s" % (landed.url or "")[:70])
            except Exception:
                pass
        log("结论：%s" % ("入口可用" if hit else "点「登录」没反应（登录入口被吞）"))
        return 0 if hit else 1
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
