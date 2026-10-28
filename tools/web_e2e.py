# -*- coding: utf-8 -*-
"""端到端验证：从 Web 界面启动真实任务，验证日志推送、等待人工、中止。

    python tools/web_e2e.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from web.server import create_app, find_free_port

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main() -> None:
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            if httpx.get(base + "/api/ping", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=EDGE, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.goto(base + "/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(800)

        print("=== 1) 填参数并启动 ===")
        page.fill("#subjectInput", "华为技术有限公司")
        # 只留第 01 项
        page.evaluate("""() => {
            document.querySelectorAll('#checklist .step-row input')
              .forEach(cb => { if (cb.value !== 'cc_shixin') cb.checked = false; });
        }""")
        page.fill("#paceInput", "0")
        page.click("#btnStart")
        page.wait_for_timeout(3000)
        start_text = page.inner_text("#btnStart")
        print("  按钮状态：", start_text, "（应为「运行中…」）")
        print("  状态胶囊：", page.inner_text("#statusChip"))

        print("=== 2) 等待日志推送 ===")
        deadline = time.time() + 90
        log_text = ""
        while time.time() < deadline:
            log_text = page.inner_text("#logBox")
            if "打开：" in log_text or "失败" in log_text or "已保存" in log_text:
                break
            time.sleep(1.5)
        print("  日志行数：", len([x for x in log_text.split("\n") if x.strip()]))
        print("  日志尾部：")
        for line in [x for x in log_text.split("\n") if x.strip()][-6:]:
            print("     ", line)

        print("=== 3) 等待人工状态 ===")
        deadline = time.time() + 90
        waiting = False
        while time.time() < deadline:
            chip = page.inner_text("#statusChip")
            if chip == "等待处理":
                waiting = True
                break
            if "已结束" in chip:
                break
            time.sleep(1.5)
        print("  状态胶囊：", page.inner_text("#statusChip"))
        resume_disabled = page.eval_on_selector(
            "#btnResume", "el => el.disabled")
        print("  【我已处理，继续截图】按钮可用：", not resume_disabled)
        if waiting:
            print("  ✔ 引擎挂起时界面进入「等待处理」，继续按钮已高亮可用")

        print("=== 4) 中止 ===")
        page.click("#btnStop")
        page.wait_for_timeout(6000)
        print("  状态胶囊：", page.inner_text("#statusChip"))
        print("  按钮状态：", page.inner_text("#btnStart"))
        log_text = page.inner_text("#logBox")
        print("  日志尾部：")
        for line in [x for x in log_text.split("\n") if x.strip()][-4:]:
            print("     ", line)

        browser.close()

    state = httpx.get(base + "/api/state", timeout=5).json()
    print("\n服务端最终状态：", state.get("state"), "结果数：", len(state.get("results", [])))


if __name__ == "__main__":
    main()
