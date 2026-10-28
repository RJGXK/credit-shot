# -*- coding: utf-8 -*-
"""真机视觉验证：用浏览器打开 Web 界面，截图存到 web_preview/。

    python tools/web_shot.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from playwright.sync_api import sync_playwright

from web.server import create_app, find_free_port

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "web_preview")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()

    base = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            import httpx
            if httpx.get(base + "/api/ping", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)

    with sync_playwright() as pw:
        # 本机没装 Playwright 自带的 Chromium，直接用系统 Edge
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        browser = pw.chromium.launch(executable_path=edge, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}
                                   ).new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(base + "/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        path = os.path.join(OUT, "01_主界面.png")
        page.screenshot(path=path, full_page=False)
        print("已截图:", path)

        # 采集项清单（统计已选数量）
        count = page.inner_text("#countText")
        print("清单计数:", count)

        # 切到人员模式
        page.click('#modeSegment .seg[data-mode="人员"]')
        page.wait_for_timeout(400)
        path = os.path.join(OUT, "02_人员模式.png")
        page.screenshot(path=path, full_page=False)
        print("已截图:", path)
        print("人员模式计数:", page.inner_text("#countText"))

        # 账号密码弹窗
        page.click("#btnCredentials")
        page.wait_for_timeout(900)
        path = os.path.join(OUT, "03_账号密码.png")
        page.screenshot(path=path, full_page=False)
        print("已截图:", path)

        # 滚轮隔离：滚日志，清单不动
        before = page.eval_on_selector("#checklist", "el => el.scrollTop")
        page.eval_on_selector("#logBox", "el => el.scrollTop = el.scrollHeight")
        page.wait_for_timeout(200)
        after = page.eval_on_selector("#checklist", "el => el.scrollTop")
        print("滚日志时清单位移:", after - before, "（应为 0）")

        browser.close()

    if errors:
        print("⚠ 前端控制台报错：")
        for e in errors[:10]:
            print("   ", e)
    else:
        print("✔ 前端无控制台错误")


if __name__ == "__main__":
    main()
