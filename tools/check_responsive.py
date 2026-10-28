# -*- coding: utf-8 -*-
"""自适应布局验证：模拟多种窗口尺寸，检查界面不裁切、不溢出。

    python tools/check_responsive.py

用 Playwright 直接开页面（等价于「在浏览器里看」这一场景），
逐个尺寸截图并检测横向溢出、关键元素可见性。

另外用 pywebview 跑一遍软件窗口场景（见 check_responsive_window.py）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "web_preview", "responsive")

SIZES = [
    (1920, 1080, "大屏"),
    (1440, 900, "常规"),
    (1180, 860, "软件窗口"),
    (1024, 768, "小屏"),
    (900, 700, "窄"),
    (760, 640, "很窄"),
]

# 页面内执行的检查脚本
PROBE_JS = r"""
(() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const doc = document.documentElement;
  const r = {
    innerW: vw, innerH: vh,
    scrollW: doc.scrollWidth,
    overflowX: doc.scrollWidth - vw,
    toolbarVisible: false,
    brandVisible: false,
    checklistVisible: false,
    logVisible: false,
    cols: '',
    overflowing: []
  };
  const layout = document.querySelector('.layout');
  if (layout) r.cols = getComputedStyle(layout).flexDirection;

  const tb = document.querySelector('.toolbar');
  if (tb) {
    const b = tb.getBoundingClientRect();
    r.toolbarVisible = b.bottom <= vh + 2 && b.top >= 0 && b.height > 0;
    r.toolbarBottom = Math.round(b.bottom);
  }
  const br = document.querySelector('.brand');
  if (br) { const b = br.getBoundingClientRect(); r.brandVisible = b.height > 0 && b.bottom <= vh; }
  const cl = document.querySelector('#checklist');
  if (cl) { const b = cl.getBoundingClientRect(); r.checklistVisible = b.height > 0 && b.width > 0; }
  const lg = document.querySelector('#logBox') || document.querySelector('.log');
  if (lg) { const b = lg.getBoundingClientRect(); r.logVisible = b.height > 0; }

  // 检查「超出视口右边界」的元素。
  // 注意：滚动容器内部的子元素即使坐标很大也不算溢出（会被容器裁掉），
  // 所以要排除位于 overflow 容器内的元素，只看真正会撑破页面的。
  const inScroller = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ov = getComputedStyle(p).overflowX;
      if (ov === 'auto' || ov === 'scroll' || ov === 'hidden') return true;
    }
    return false;
  };
  document.querySelectorAll(
    '.card, .btn, .step-row, .site-head, .field-row input, .cred-table, .toolbar, .statusbar'
  ).forEach((el) => {
    const b = el.getBoundingClientRect();
    if (b.width > 0 && b.right > vw + 2 && !inScroller(el)) {
      r.overflowing.push((el.className || el.tagName) + ' right=' + Math.round(b.right));
    }
  });
  r.overflowing = r.overflowing.slice(0, 6);

  // 窄屏单列布局下，右栏是否还能滚动到（不能被永久挡住）
  const lay = document.querySelector('.layout');
  r.layoutScrollable = lay ? (lay.scrollHeight > lay.clientHeight + 2) : false;
  r.layoutScrollH = lay ? lay.scrollHeight : 0;
  r.layoutClientH = lay ? lay.clientHeight : 0;
  return JSON.stringify(r);
})()
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    from web.server import find_free_port, serve
    import uvicorn
    from web.server import create_app

    os.makedirs(OUT, exist_ok=True)
    port = find_free_port(start=8799)
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()

    # 等服务起来
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = "http://127.0.0.1:%d/" % port
    for _ in range(30):
        try:
            with opener.open(url + "api/ping", timeout=1) as r:
                if b"credit-shot" in r.read():
                    break
        except Exception:
            time.sleep(0.5)

    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    results = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=edge)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1500)

        for w, h, label in SIZES:
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(700)
            data = json.loads(page.evaluate(PROBE_JS))
            results[label] = data
            page.screenshot(path=os.path.join(OUT, "%s_%dx%d.png" % (label, w, h)))
            print("\n=== %s（%d×%d）===" % (label, w, h))
            print("   视口 %sx%s  横向溢出 %spx  布局方向 %s"
                  % (data["innerW"], data["innerH"], data["overflowX"], data["cols"]))
            print("   工具栏=%s 品牌条=%s 清单=%s 日志=%s"
                  % (data["toolbarVisible"], data["brandVisible"],
                     data["checklistVisible"], data["logVisible"]))
            if data["overflowing"]:
                print("   ⚠ 超宽元素：%s" % data["overflowing"])

        # 顺带看看凭据弹窗在各尺寸下的表现
        page.set_viewport_size({"width": 1180, "height": 860})
        page.wait_for_timeout(500)
        page.click("#btnCredentials")
        page.wait_for_timeout(1200)
        for w, h, label in ((1180, 860, "常规"), (760, 640, "很窄")):
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(700)
            data = json.loads(page.evaluate(PROBE_JS))
            page.screenshot(path=os.path.join(OUT, "凭据弹窗_%s_%dx%d.png" % (label, w, h)))
            over = page.evaluate("""() => {
              const dlg = document.querySelector('dialog');
              if (!dlg) return 'no-dialog';
              const b = dlg.getBoundingClientRect();
              return {right: Math.round(b.right), vw: window.innerWidth,
                      scrollW: document.querySelector('.cred-table').scrollWidth,
                      tableW: Math.round(document.querySelector('.cred-table').getBoundingClientRect().width)};
            }""")
            print("\n--- 凭据弹窗 %s（%d×%d）---" % (label, w, h))
            print("   ", over)

        browser.close()

    print("\n" + "=" * 62)
    ok = True
    for label, data in results.items():
        problems = []
        if data["overflowX"] > 2:
            problems.append("横向溢出 %spx" % data["overflowX"])
        if not data["toolbarVisible"]:
            problems.append("工具栏不可见")
        if not data["brandVisible"]:
            problems.append("品牌条不可见")
        if data["overflowing"]:
            problems.append("%d 个元素超宽" % len(data["overflowing"]))
        if problems:
            ok = False
            print("✘ %-10s %s" % (label, "；".join(problems)))
        else:
            print("✔ %-10s 视口 %sx%s 布局 %s"
                  % (label, data["innerW"], data["innerH"], data["cols"]))
    print("\n截图目录：%s" % OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
