# -*- coding: utf-8 -*-
"""量一量打包后的 exe 打开后，网页视口到底有多少像素。

    python tools/measure_viewport.py

背景：
  pywebview 的窗口尺寸与网页视口尺寸不是一回事（边框、缩放都会吃掉一部分），
  界面的底部工具栏曾经因此被裁掉。这个脚本直接把真实视口量出来，
  用来核对 `desktop_window._window_chrome()` 的补偿值对不对。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 期望的网页视口尺寸（CSS 像素）
EXPECT_W, EXPECT_H = 1180, 860


def main() -> int:
    import webview

    import desktop_window
    from web.server import serve

    port = 8797
    url = "http://127.0.0.1:%d/" % port
    threading.Thread(
        target=lambda: serve(host="127.0.0.1", port=port, open_ui=False),
        daemon=True).start()
    desktop_window._wait_for_service(url, timeout=30)

    result = {}

    def probe():
        time.sleep(9)
        try:
            win = webview.windows[0]
            # 等窗口能执行 JS
            for _ in range(20):
                try:
                    win.evaluate_js("1")
                    break
                except Exception:
                    time.sleep(1.5)
            raw = win.evaluate_js(
                "JSON.stringify({innerW: innerWidth, innerH: innerHeight, "
                "dpr: devicePixelRatio, bodyH: document.body.scrollHeight, "
                "bodyW: document.body.scrollWidth})")
            result.update(json.loads(raw))
        except Exception as exc:
            result["error"] = str(exc)

    def closer():
        # 等测量完再关窗，避免脚本一直挂着不退
        for _ in range(60):
            if result:
                break
            time.sleep(1)
        time.sleep(1.5)
        try:
            webview.windows[0].destroy()
        except Exception:
            pass

    threading.Thread(target=probe, daemon=True).start()
    threading.Thread(target=closer, daemon=True).start()
    desktop_window.open_window(url, title="视口测量")
    print("视口实测：", result)

    w = result.get("innerW")
    h = result.get("innerH")
    if not w or not h:
        print("✘ 没能测到视口")
        return 1
    ok = (w >= EXPECT_W - 20) and (h >= EXPECT_H - 20)
    print("%s 视口 %d×%d（期望 ≥%d×%d）"
          % ("✔" if ok else "✘", w, h, EXPECT_W, EXPECT_H))

    # 屏幕不够高时，窗口本来就会矮一截（内容自适应，不裁切）——
    # 这时按屏幕允许的最大视口来判定。
    import desktop_window
    wa_w, wa_h = desktop_window._work_area()
    scale = desktop_window._display_scale()
    cw, ch = desktop_window._window_chrome()
    max_w = int(wa_w / scale * 0.95) - cw
    max_h = int(wa_h / scale * 0.95) - ch
    if h < EXPECT_H - 20 and h >= max_h - 20:
        print("   （本机屏幕高度只允许 %d 的视口，窗口已按屏幕自适应）" % max_h)
    return 0 if ok or (h >= max_h - 20) else 1


if __name__ == "__main__":
    sys.exit(main())
