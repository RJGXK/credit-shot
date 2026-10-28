# -*- coding: utf-8 -*-
"""抓 CNCA 结果页真实 HTML，确认服务端渲染的输入框取值。"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)

URL = ("https://cx.cnca.cn/CertECloud/result/skipResultList"
       "?certNumber=&orgName=%E4%B8%AD%E7%91%9E%E7%9B%9B%E4%B8%96"
       "%EF%BC%88%E5%8C%97%E4%BA%AC%EF%BC%89%E5%BB%BA%E7%AD%91%E6%9C%89"
       "%E9%99%90%E5%85%AC%E5%8F%B8&fromIndex=true")


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        html = page.content()
        with open(os.path.join(OUT, "skiplist.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print("HTML 长度", len(html))

        for kw in ["orgName", "certNumber", "fromIndex", "certItem", "isSelf",
                   "orgContent", "certContent", "orgListDiv", "certWarn",
                   "orgWarn", "captcha"]:
            print("\n===== %s =====" % kw)
            for m in re.finditer(kw, html):
                s = max(0, m.start() - 160)
                print("   ...", html[s:m.start() + 120].replace("\n", " "))
                break
            # 输入框
            for m in re.finditer(r'<input[^>]*' + kw + r'[^>]*>', html, re.I):
                print("   INPUT:", m.group(0)[:220])
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
