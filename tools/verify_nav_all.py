# -*- coding: utf-8 -*-
"""真机验证全部 7 个站点的「上级目录跳转」是否都能落地。

判据：跳转后页面有正文（不是白页）、标题非空、URL 属于目标站。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav
from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")

SITES = [
    ("gsxt", "国家企业信用信息公示系统"),
    ("creditchina", "信用中国"),
    ("ccgp", "中国政府采购网"),
    ("mohurd", "住建部"),
    ("plap", "军队采购网"),
    ("zxgk", "失信被执行人"),
    ("wenshu", "裁判文书网"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    ok_n = 0
    try:
        for key, name in SITES:
            print("\n--- %s (%s) ---" % (name, key))
            res = nav.goto_via_landing(page, key, log=print, timeout_ms=60000)
            p = res.get("page") or page
            time.sleep(1.0)
            st = nav.nav_state(p)
            good = bool(st.get("len", 0) > 200 and not st.get("blank"))
            print("  ok=%s | url=%s | title=%s | len=%s"
                  % (res.get("ok"), str(st.get("url"))[:62],
                     str(st.get("title"))[:26], st.get("len")))
            if good:
                ok_n += 1
                try:
                    page.screenshot(path=os.path.join(OUT, "nav_%s.png" % key))
                except Exception:
                    pass
            else:
                print("  ✘ 落地失败：%s" % res.get("reason", ""))
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass
    print("\n===== 跳转成功 %d/%d =====" % (ok_n, len(SITES)))


if __name__ == "__main__":
    main()
