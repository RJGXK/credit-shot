# -*- coding: utf-8 -*-
"""登录页取证 v2：点击「登录」后跟踪所有标签页变化 + 每 5 秒尽力快照。

不依赖 evaluate 成功；每个标签页尽力读 URL/截图。弹出的新标签（shiming）
就是观察对象。最后把所有截图留在 tools/_login_forensics/。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_login_forensics")
os.makedirs(OUT, exist_ok=True)


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()

    console_lines = []
    failures = []
    def on_console(msg):
        t = (msg.text or "")
        console_lines.append("[%s] %s" % (msg.type, t[:150]))
    def on_response(resp):
        try:
            if resp.status >= 400:
                failures.append("[%d] %s" % (resp.status, resp.url[:110]))
        except Exception:
            pass
    try:
        page.on("console", on_console)
        page.on("response", on_response)
    except Exception:
        pass

    try:
        log("=== 1) 入口进首页 ===")
        res = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                   timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            log("入口失败")
            return 1

        log("=== 2) 点击「登录」===")
        import json
        r = landed.evaluate("""()=>{
          const norm=s=>(s||'').replace(/\\s+/g,'').trim();
          const hit=[...document.querySelectorAll('a,span,div,li,button')]
            .find(e=>{
              const t=norm(e.innerText||e.textContent||'');
              if(t!=='登录') return false;
              const b=e.getBoundingClientRect();
              return b.width>0&&b.height>0;});
          if(!hit) return 'NONE';
          hit.scrollIntoView({block:'center'});
          const b=hit.getBoundingClientRect();
          return JSON.stringify({cx:b.left+b.width/2, cy:b.top+b.height/2});
        }""")
        if not (isinstance(r, str) and r.startswith("{")):
            log("没有「登录」入口")
            return 1
        d = json.loads(r)
        landed.mouse.click(d["cx"], d["cy"])
        log("已点击。跟踪 40 秒标签页变化（每 5 秒快照）…")

        for i in range(8):
            time.sleep(5)
            log("--- t=%ds ---" % ((i + 1) * 5))
            pages = []
            try:
                pages = list(ctx.pages)
            except Exception:
                pass
            for idx, p in enumerate(pages):
                try:
                    u = p.url or ""
                except Exception:
                    u = "<不可读>"
                short = u[:80]
                log("  tab[%d] %s" % (idx, short))
                if "shiming" in u:
                    try:
                        body = p.evaluate(
                            "()=>(document.body?document.body.innerText:"
                            "'').replace(/\\s+/g,' ').slice(0,200)")
                        log("     正文：%s" % body)
                        n_input = p.evaluate(
                            "()=>document.querySelectorAll('input').length")
                        n_input_user = p.evaluate(
                            "()=>document.getElementById('UserName')?1:0")
                        log("     input总数=%s UserName=%s"
                            % (n_input, n_input_user))
                        shot = os.path.join(OUT, "shiming_t%d.png" % ((i + 1) * 5))
                        p.screenshot(path=shot)
                    except Exception as exc:
                        log("     读取失败：%s" % str(exc)[:60])
        log("")
        log("=== 请求失败（HTTP>=400）===")
        for f in failures[-12:]:
            log("  %s" % f)
        if not failures:
            log("  （无）")
        log("")
        log("=== 控制台（全部，最后 12 条）===")
        for c in console_lines[-12:]:
            log("  %s" % c)
        return 0
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
