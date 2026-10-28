# -*- coding: utf-8 -*-
"""布局溢出自测：确保页面内容不超出视口（底部不被裁）。

背景：右栏两张卡片原来用百分比 basis（flex: 1 1 58% / 42%），
百分比基准是父容器高度、父容器高度又是 auto（按内容撑开），
形成循环放大 → 右栏高度 1413px 远超视口 815px，底部工具栏被裁掉。
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PORT = 8775
BASE = "http://127.0.0.1:%d" % PORT
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

#: 视口尺寸 → 期望「无溢出」的关键容器
SIZES = [
    (1440, 900, "大屏"),
    (1180, 815, "软件窗口"),
    (1024, 700, "窄一些"),
    (900, 640, "临界"),
    (760, 600, "很窄"),
]

PROBE = """() => {
  const r = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return { top: Math.round(b.top), bottom: Math.round(b.bottom),
             h: Math.round(b.height) };
  };
  return {
    innerH: window.innerHeight,
    innerW: window.innerWidth,
    body: r('body'), layout: r('.layout'),
    colRight: r('.col-right'), cardGrow: r('.card-grow'), cardLog: r('.card-log'),
    checklist: r('#checklist'), toolbar: r('.toolbar'), statusbar: r('.statusbar'),
    colLeft: r('.col-left')
  };
}"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    srv = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; sys.path.insert(0, %r);"
         "from web.server import serve;"
         "serve(host='127.0.0.1', port=%d, open_ui=False)" % (ROOT, PORT)],
        cwd=ROOT)
    fails = []
    try:
        for _ in range(60):
            try:
                with OP.open(BASE + "/api/ping", timeout=1) as r:
                    if b"credit-shot" in r.read():
                        break
            except Exception:
                time.sleep(1)

        with sync_playwright() as p:
            b = p.chromium.launch(
                executable_path=r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                args=["--remote-debugging-port=9407"])
            for w, h, label in SIZES:
                pg = b.new_page(viewport={"width": w, "height": h})
                pg.goto(BASE + "/", wait_until="networkidle")
                pg.wait_for_timeout(1500)
                d = pg.evaluate(PROBE)
                inner = d["innerH"]
                over_right = d["colRight"]["bottom"] - inner
                over_list = d["checklist"]["bottom"] - inner
                over_tool = d["toolbar"]["bottom"] - inner
                ok = over_right <= 1 and over_tool <= 1
                print("=== %s %dx%d ===" % (label, w, h))
                print("   视口高 %d | .layout h=%d | .col-right h=%d | #checklist h=%d"
                      % (inner, d["layout"]["h"], d["colRight"]["h"],
                         d["checklist"]["h"]))
                print("   右栏超出视口 %+d px   清单超出 %+d px   工具栏超出 %+d px"
                      % (over_right, over_list, over_tool))
                print("   %s %s" % ("✔" if ok else "✘",
                                   "无溢出" if ok else "存在溢出"))
                if not ok:
                    fails.append(label)
                pg.close()
            b.close()
        print()
        if fails:
            print("✘ 有溢出的尺寸：%s" % "、".join(fails))
            return 1
        print("✔ 所有尺寸均无垂直溢出")
        return 0
    finally:
        try:
            srv.kill()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
