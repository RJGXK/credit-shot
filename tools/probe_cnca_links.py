# -*- coding: utf-8 -*-
"""列出国家认监委官网上所有指向 cx.cnca.cn 的链接，用来挑最稳的入口。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

LANDINGS = [
    "https://www.cnca.gov.cn/",
    "https://www.cnca.gov.cn/xxgk/",
    "https://www.cnca.gov.cn/zwxx/",
]


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        for url in LANDINGS:
            print("\n===== %s =====" % url)
            try:
                nav = __import__("core.nav", fromlist=["nav"])
                nav.goto(page, url, timeout_ms=45000, log=print)
            except Exception as exc:
                print("  打开失败:", str(exc).splitlines()[0][:80])
                continue
            time.sleep(3)
            links = page.evaluate("""()=>{
              return [...document.querySelectorAll('a[href]')]
                .map(a=>({t:(a.innerText||a.textContent||'').replace(/\\s+/g,' ').trim().slice(0,40),
                          h:a.href, target:a.target||''}))
                .filter(x=>/cx\\.cnca\\.cn|CertECloud/i.test(x.h));
            }""")
            if not links:
                print("  （没有指向 cx.cnca.cn 的链接）")
                continue
            for l in links[:15]:
                print("  %-42s %s%s" % (l["t"][:40], l["h"][:100],
                                        "  [target=%s]" % l["target"] if l["target"] else ""))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
