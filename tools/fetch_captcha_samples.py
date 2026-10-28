# -*- coding: utf-8 -*-
"""抓一批信用中国验证码样本，供离线评估「预处理 + 识别」组合的准确率。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "samples")
os.makedirs(OUT, exist_ok=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=lambda s: None, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=lambda s: None)
        page.wait_for_timeout(3500)
        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text("中瑞盛世（北京）建筑有限公司")
            page.wait_for_timeout(500)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")
        page.wait_for_timeout(3500)
        for i in range(n):
            src = page.evaluate("()=>{const e=document.getElementById('vcodeimg');"
                                " return e? e.src : '';}")
            if not src:
                print("没有验证码图片")
                break
            # 每次换一张，避免服务端复用
            page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                          " if(s) s.click();}")
            page.wait_for_timeout(1200)
            src = page.evaluate("()=>{const e=document.getElementById('vcodeimg');"
                                " return e? e.src : '';}")
            resp = page.request.get(src, headers={"Accept": "image/*,*/*;q=0.8",
                                                  "Referer": "https://www.creditchina.gov.cn/"})
            body = resp.body()
            fn = os.path.join(OUT, "s%02d.jpg" % (i + 1))
            open(fn, "wb").write(body)
            print("样本 %d: status=%s ct=%s len=%d -> %s"
                  % (i + 1, resp.status, resp.headers.get("content-type"), len(body), fn))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
