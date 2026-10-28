# -*- coding: utf-8 -*-
"""站点跳转条自测：起服务 → 打开界面 → 点「裁判文书」→ 验证定位。

一条命令内完成，避免后台服务进程被回收。
"""
import os
import subprocess
import sys
import time

import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PORT = 8771
BASE = "http://127.0.0.1:%d" % PORT

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    from playwright.sync_api import sync_playwright

    srv = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; sys.path.insert(0, %r);"
         "from web.server import serve;"
         "serve(host='127.0.0.1', port=%d, open_ui=False)" % (ROOT, PORT)],
        cwd=ROOT)
    try:
        # 等服务就绪
        ok = False
        for _ in range(60):
            try:
                with OP.open(BASE + "/api/ping", timeout=1) as r:
                    if b"credit-shot" in r.read():
                        ok = True
                        break
            except Exception:
                time.sleep(1)
        if not ok:
            print("✘ 服务未就绪")
            return 1
        print("✔ 服务已就绪 %s" % BASE)

        with sync_playwright() as p:
            b = p.chromium.launch(
                executable_path=r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                args=["--remote-debugging-port=9405"])
            pg = b.new_page(viewport={"width": 1180, "height": 815})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(BASE + "/", wait_until="networkidle")
            pg.wait_for_timeout(2000)

            btns = pg.evaluate("() => Array.from(document.querySelectorAll('.jump-btn')).map(b=>b.textContent)")
            print("跳转条按钮：", btns)
            assert len(btns) == 7, "按钮数不对"

            before = pg.evaluate("() => document.querySelector('#checklist').scrollTop")
            pg.click(".jump-btn:nth-child(7)")      # 裁判文书
            pg.wait_for_timeout(900)
            after = pg.evaluate("""() => {
              const box = document.querySelector('#checklist');
              const blk = document.getElementById('site-wenshu');
              const r = blk.getBoundingClientRect(), br = box.getBoundingClientRect();
              const steps = Array.from(blk.querySelectorAll('.step-row'));
              const lastStep = steps[steps.length-1].getBoundingClientRect();
              return { scrollTop: Math.round(box.scrollTop),
                       maxScroll: Math.round(box.scrollHeight - box.clientHeight),
                       name: blk.querySelector('.site-name').textContent.trim(),
                       headVisible: r.top >= br.top - 1 && r.top < br.bottom,
                       lastStepVisible: lastStep.bottom <= br.bottom + 1 && lastStep.top < br.bottom,
                       flash: blk.classList.contains('flash') };
            }""")
            print("点击前 scrollTop =", before)
            print("点击后：", after)
            probe = """() => {
              const box = document.querySelector('#checklist');
              const blk = document.getElementById('site-wenshu');
              const r = blk.getBoundingClientRect(), br = box.getBoundingClientRect();
              const s26 = blk.querySelectorAll('.step-row')[0].getBoundingClientRect();
              return { scrollTop: Math.round(box.scrollTop),
                       maxScroll: Math.round(box.scrollHeight - box.clientHeight),
                       boxTop: Math.round(br.top), boxBottom: Math.round(br.bottom),
                       boxH: Math.round(br.height),
                       blkTop: Math.round(r.top), blkBottom: Math.round(r.bottom),
                       s26Top: Math.round(s26.top), s26Bottom: Math.round(s26.bottom),
                       innerH: window.innerHeight };
            }"""
            print("测量A：", pg.evaluate(probe))
            pg.screenshot(path=os.path.join(ROOT, "dist", "_jump.png"))
            print("测量B（截图后）：", pg.evaluate(probe))
            print("JS 错误：", errs or "无")
            b.close()

        good = (after["headVisible"] and after["lastStepVisible"]
                and after["scrollTop"] > before and not errs)
        print("\n%s 跳转定位到「中国裁判文书网」（标题与 3 个采集项全部可见）"
              % ("✔" if good else "✘"))
        return 0 if good else 1
    finally:
        try:
            srv.kill()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
