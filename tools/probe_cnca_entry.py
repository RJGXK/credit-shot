# -*- coding: utf-8 -*-
"""诊断：CNCA 入口链每一步到底落在哪个页面。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav
from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)


def probe(page, tag):
    try:
        info = page.evaluate("""()=>({
          title:document.title,
          len:(document.body?document.body.innerText||'':'').trim().length,
          head:(document.body?((document.body.innerText||'')
            .replace(/\\s+/g,' ').slice(0,120)):''),
          orgName:!!document.getElementById('orgName'),
          inputs:document.querySelectorAll('input').length,
          scripts:document.querySelectorAll('script[src]').length,
        })""")
    except Exception as exc:
        info = {"error": str(exc).splitlines()[0][:80]}
    print("  [%s] url=%s" % (tag, (page.url or "")[:130]))
    print("       %s" % json.dumps(info, ensure_ascii=False)[:300])
    return info


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()

        print("=== A) 直达 cx.cnca.cn 首页 ===")
        nav.goto(page, "https://cx.cnca.cn/CertECloud/index/index/page",
                 timeout_ms=60000, log=print)
        time.sleep(4)
        probe(page, "直达")

        print("\n=== B) 走入口链 ===")
        res = nav.goto_via_landing(page, "cnca", log=print, timeout_ms=60000)
        page = res.get("page") or page
        print("  ok=%s via=%s" % (res.get("ok"), res.get("via")))
        probe(page, "入口链结果")

        print("\n=== C) 认监委官网页面上的链接 ===")
        nav.goto(page, "https://www.cnca.gov.cn/", timeout_ms=60000, log=print)
        time.sleep(3)
        links = page.evaluate("""()=>[...document.querySelectorAll('a')]
          .map(a=>({t:(a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30),
                    h:a.href}))
          .filter(x=>/cx\\.cnca\\.cn|认证认可|查询/.test(x.h+' '+x.t))
          .slice(0,12)""")
        for l in links:
            print("   ", json.dumps(l, ensure_ascii=False)[:180])
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
