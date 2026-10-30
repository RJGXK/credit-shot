# -*- coding: utf-8 -*-
"""登录卡点取证探针：填值→提交后每 5 秒快照页面状态+截图+控制台错误。

不自动关浏览器（人工可继续操作）；输出到 tools/_login_forensics/ 目录：
  snapshot_NNN.txt  每次快照（URL/正文前 200 字/输入框值/验证码面板/按钮状态）
  shot_NNN.png      同一时刻的页面截图
最后 5 分钟内浏览器保持打开，人工可手动试登录。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402
from core.page import fill_controlled     # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_login_forensics")
os.makedirs(OUT, exist_ok=True)

COMPANY = "中瑞盛世（北京）建筑有限公司"


def log(msg: str) -> None:
    print(msg, flush=True)


def creds():
    from auth.credentials import load_credentials
    for c in (load_credentials() or []):
        if getattr(c, "platform", "") == "gsxt" and getattr(c, "usable", False):
            return str(c.username), str(c.password)
    return "", ""


def open_login(page) -> bool:
    js = """
    ()=>{
      if(document.getElementById('UserName')) return 'ALREADY';
      const norm=s=>(s||'').replace(/\\s+/g,'').trim();
      const els=[...document.querySelectorAll('a,span,div,li,button')];
      const hit=els.find(e=>{
        const t=norm(e.innerText||e.textContent||'');
        if(t!=='登录') return false;
        const b=e.getBoundingClientRect();
        return b.width>0&&b.height>0;});
      if(!hit) return 'NONE';
      hit.scrollIntoView({block:'center'});
      const b=hit.getBoundingClientRect();
      return JSON.stringify({cx:b.left+b.width/2, cy:b.top+b.height/2});
    }"""
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            r = page.evaluate(js)
        except Exception:
            r = None
        if r == "ALREADY":
            return True
        if isinstance(r, str) and r.startswith("{"):
            import json
            d = json.loads(r)
            try:
                page.mouse.click(d["cx"], d["cy"])
            except Exception:
                return False
            d2 = time.time() + 15
            while time.time() < d2:
                time.sleep(1.5)
                try:
                    if page.evaluate("()=>!!document.getElementById('UserName')"):
                        return True
                except Exception:
                    pass
        time.sleep(1.5)
    return False


SNAP_JS = """
()=>{
  const gt=(sel)=>{
    const e=document.querySelector(sel);
    if(!e) return false;
    const b=e.getBoundingClientRect(); const s=getComputedStyle(e);
    return b.width>30&&b.height>30&&s.display!=='none'&&s.visibility!=='hidden';
  };
  const err=(document.querySelector('.errMsg,.error-msg,.toast,.layui-layer-content')
             ||{}).innerText||'';
  return {
    url:location.href,
    title:document.title||'',
    uname:(document.getElementById('UserName')||{}).value||'',
    upwd:!!(document.getElementById('gsxtp')||{}).value,
    gtPanel:gt('.geetest_panel_box')||gt('.geetest_window')||gt('.geetest_holder'),
    gtAny:!!document.querySelector('[class*=geetest]'),
    err:err.slice(0,80),
    body:b0=>0,
    text:(document.body&&document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)
  };
}
"""


def snapshot(page, n, console_lines):
    try:
        st = page.evaluate(SNAP_JS)
    except Exception as e:
        st = {"err": "eval:%s" % str(e)[:60]}
    shot = os.path.join(OUT, "shot_%03d.png" % n)
    try:
        page.screenshot(path=shot)
    except Exception:
        shot = "(截图失败)"
    with open(os.path.join(OUT, "snapshot_%03d.txt" % n), "w",
              encoding="utf-8") as f:
        f.write("t=%.1fs\n" % (time.time() - T0))
        for k, v in st.items():
            f.write("%s: %s\n" % (k, v))
        f.write("console:\n")
        f.write("\n".join(console_lines[-15:]) or "(无)")
    log("  [%03d] url=%s 已填账号=%s 有密码=%s gtPanel=%s gtAny=%s err=%s"
        % (n, str(st.get("url"))[:60], bool(st.get("uname")),
           st.get("upwd"), st.get("gtPanel"), st.get("gtAny"),
           st.get("err") or "-"))
    return st


T0 = time.time()


def main() -> int:
    u, p = creds()
    log("凭据：%s" % (u[:3] + "****" + u[-4:] if len(u) >= 7 else "未配置"))
    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()

    console_lines = []
    def on_console(msg):
        t = (msg.text or "")
        if any(k in t.lower() for k in ("error", "fail", "forbidden", "captcha",
                                        "geetest", "异常")):
            console_lines.append("[%s] %s" % (msg.type, t[:160]))
    def on_error(err):
        console_lines.append("[pageerror] %s" % str(err)[:160])
    try:
        page.on("console", on_console)
        page.on("pageerror", on_error)
    except Exception:
        pass

    try:
        log("=== 1) 入口进首页 ===")
        res = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                   timeout_ms=45000)
        landed = res.get("page") or page
        if not res.get("ok"):
            log("入口失败")
            return 1
        log("=== 2) 点【登录】===")
        if not open_login(landed):
            log("打不开登录页")
            return 1
        time.sleep(1.2)
        log("=== 3) 填值（逐字符 insertText）===")
        ok_u = fill_controlled(landed, "() => document.getElementById('UserName')", u)
        time.sleep(0.4)
        ok_p = fill_controlled(landed, "() => document.getElementById('gsxtp')", p)
        log("填值：账号=%s 密码=%s" % (ok_u, ok_p))
        n = 0
        snapshot(landed, n, console_lines); n += 1

        log("=== 4) 提交（真实点击 #btn_login）===")
        try:
            loc = landed.locator("#btn_login").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            log("已点击提交")
        except Exception as exc:
            log("提交失败：%s" % str(exc)[:60])
        log("=== 5) 每 5 秒快照一次，共 8 次（40 秒）===")
        logged_in = False
        for i in range(8):
            time.sleep(5)
            st = snapshot(landed, n, console_lines); n += 1
            try:
                cur = landed.url or ""
            except Exception:
                cur = ""
            if st.get("gtPanel"):
                log("  >>> 极验面板可见：请在浏览器窗口完成验证！<<<")
            if "shiming" not in cur and "gsxt.gov.cn" in cur:
                logged_in = True
                log("  ✔ URL 已跳回首页（登录成功）")
                break
            if st.get("err"):
                log("  ⚠ 页面错误提示：%s" % st.get("err"))
        if not logged_in:
            log("")
            log("=== 6) 未自动判定成功。浏览器保持打开 5 分钟，请手动试登录 ===")
            log("（手动登录成功后按 Ctrl+C 结束本探针即可）")
            for i in range(30):
                time.sleep(10)
                try:
                    cur = landed.url or ""
                except Exception:
                    break
                st = snapshot(landed, n, console_lines); n += 1
                if "shiming" not in cur and "gsxt.gov.cn" in cur:
                    st2 = landed.evaluate(
                        "()=>/退出登录|个人中心|欢迎您/.test(document.body.innerText)")
                    if st2:
                        log("  ✔ 手动登录成功！")
                        logged_in = True
                        break
        log("")
        log("=== 最终：%s ===" % ("登录成功" if logged_in else "未能登录（见取证目录）"))
        log("取证文件：%s" % OUT)
        if logged_in:
            log("=== 7) 登录成功 → 验证查询是否放行 ===")
            time.sleep(2)
            res2 = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                        timeout_ms=45000)
            lp = res2.get("page") or page
            if res2.get("ok") and fill_controlled(
                    lp, "() => document.getElementById('keyword')", COMPANY):
                time.sleep(0.8)
                try:
                    loc = lp.locator("#btn_query").first
                    loc.scroll_into_view_if_needed(timeout=3000)
                    loc.click(timeout=5000)
                    verdict = "✘ 无反应"
                    deadline = time.time() + 16
                    while time.time() < deadline:
                        try:
                            r = lp.evaluate("""()=>{
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
                    log("登录态查询判定：%s" % verdict)
                except Exception as exc:
                    log("查询异常：%s" % str(exc)[:60])
        return 0
    finally:
        # 不关浏览器：人工可继续观察/操作
        log("（浏览器保持打开；探针结束，未关闭 CDP 连接）")


if __name__ == "__main__":
    sys.exit(main())
