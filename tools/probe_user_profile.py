# -*- coding: utf-8 -*-
"""终极对照实验：用【用户自己的 Edge 默认 Profile】（非软件 Profile）跑自动化。

目的：切分「自动化操作」与「会话身份」两个变量——
  · 若用户 Profile + 自动化 = 查询/登录正常 → 软件专属 Profile 的会话已被
    WAF 拉黑（换身份即愈：改用用户 Profile 或重建 Profile）；
  · 若用户 Profile + 自动化 = 同样被吞 → 自动化操作本身（CDP/鼠标事件）
    被识别（需换隐匿方案）。
注意：**必须先完全退出用户的 Edge**（同一 Profile 不允许双开）。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright   # noqa: E402

COMPANY = "中瑞盛世（北京）建筑有限公司"
# 用户 Edge 默认 Profile（Win10/11 标准位置；找不到会明确报错）
USER_PROFILE = os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\Edge\User Data")


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    if not os.path.isdir(USER_PROFILE):
        log("⚠ 未找到用户 Edge Profile：%s" % USER_PROFILE)
        return 1
    import socket
    port = 9340
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            log("⚠ 端口 %d 已被占用——请先完全退出你的 Edge 浏览器再跑本探针"
                % port)
            return 1

    exe = None
    for cand in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(cand):
            exe = cand
            break
    if not exe:
        log("未找到 msedge.exe")
        return 1

    log("=== 用你的 Edge 默认 Profile 启动（自动化接管）===")
    import subprocess
    proc = subprocess.Popen(
        [exe, "--remote-debugging-port=%d" % port,
         "--profile-directory=Default",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % port)
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.set_default_timeout(30000)
        except Exception:
            pass

        log("=== 1) 首页登录态检查（你的 Profile 里有登录 Cookie）===")
        page.goto("https://www.gsxt.gov.cn/index.html", timeout=45000,
                  wait_until="domcontentloaded")
        time.sleep(8)
        st = page.evaluate("""()=>{
          const b=(document.body&&document.body.innerText)||'';
          return {logged:/退出登录|个人中心|欢迎您|安全退出/.test(b),
                  hasKw:!!document.getElementById('keyword'),
                  text:b.replace(/\\s+/g,' ').slice(0,120)};
        }""")
        log("已登录=%s 搜索框=%s" % (st.get("logged"), st.get("hasKw")))
        log("正文：%s" % st.get("text", "")[:110])

        log("=== 2) 查询测试（你的会话）===")
        if st.get("hasKw"):
            page.evaluate("""(name)=>{
              const el=document.getElementById('keyword');
              const set=Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,'value').set;
              el.focus(); set.call(el,name);
              el.dispatchEvent(new Event('input',{bubbles:true}));
              el.dispatchEvent(new Event('change',{bubbles:true}));
            }""", COMPANY)
            time.sleep(1.0)
            try:
                loc = page.locator("#btn_query").first
                loc.scroll_into_view_if_needed(timeout=3000)
                loc.click(timeout=5000)
                log("点击：TRUSTED_CLICK")
            except Exception as exc:
                log("点击失败：%s" % str(exc)[:60])
            verdict = "✘ 无反应"
            deadline = time.time() + 16
            while time.time() < deadline:
                try:
                    r = page.evaluate("""()=>{
                      const sel='.geetest_panel_box,.geetest_window,.geetest_holder';
                      const e=document.querySelector(sel);
                      let vis=false;
                      if(e){const b=e.getBoundingClientRect();
                            vis=b.width>50&&b.height>40;}
                      return {listing:/corp-query-search/.test(location.href),
                              vis:vis};
                    }""")
                except Exception:
                    r = {}
                if r.get("listing"):
                    verdict = "✔ 跳到结果页（放行）"
                    break
                if r.get("vis"):
                    verdict = "✔ 极验弹出（放行）"
                    break
                time.sleep(2)
            log("查询判定：%s" % verdict)
        else:
            log("⚠ 你的 Profile 首页连搜索框都没有（可能也在挑战页）")
        log("")
        log("=== 结论 ===")
        log("用户 Profile + 自动化 → 见上（若正常则证明软件 Profile 会话已被拉黑）")
        return 0
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
