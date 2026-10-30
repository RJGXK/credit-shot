# -*- coding: utf-8 -*-
"""实测「软件 Profile 登录 → 查询放行」全链路。

流程：入口 → 首页点【登录】→ 自动填账号密码（逐字符）→ 挂起等人工过极验
→ 判定登录成功 → 回首页 → 查询 → 判定放行。
账号密码从引擎凭据配置读取（auth.credentials）。
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402
from core.page import fill_controlled     # noqa: E402

COMPANY = "中瑞盛世（北京）建筑有限公司"


def log(msg: str) -> None:
    print(msg, flush=True)


def creds():
    try:
        from auth.credentials import load_credentials
        for c in (load_credentials() or []):
            if getattr(c, "platform", "") == "gsxt" and getattr(c, "usable", False):
                return str(c.username), str(c.password)
        return "", ""
    except Exception as exc:
        log("读凭据失败：%s" % str(exc)[:60])
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


def fill_creds(page, u, p) -> bool:
    # 调试：列出登录页实际输入框（找不到 #UserName 时能看出真实结构）
    try:
        fields = page.evaluate("""()=>{
          return [...document.querySelectorAll('input')].map(e=>({
            id:e.id, name:e.name||'', type:e.type||'',
            ph:e.placeholder||''}));
        }""")
        log("登录页输入框：%s" % fields)
    except Exception:
        pass
    ok_u = fill_controlled(page, "() => document.getElementById('UserName')", u)
    time.sleep(random.uniform(0.3, 0.6))
    ok_p = fill_controlled(page, "() => document.getElementById('gsxtp')", p)
    if ok_u and ok_p:
        return True
    # 兜底：按 type 找（手机号=text，密码=password）
    try:
        fields2 = page.evaluate("""()=>{
          const t=[...document.querySelectorAll('input[type=text],input:not([type])')]
            .find(e=>e.getBoundingClientRect().width>0);
          const p2=[...document.querySelectorAll('input[type=password]')]
            .find(e=>e.getBoundingClientRect().width>0);
          return {tid:t?t.id:'', pid:p2?p2.id:'', tlen:t?1:0, plen:p2?1:0};
        }""")
        log("兜底探测：%s" % fields2)
        if fields2.get("tlen") and fields2.get("plen"):
            ok_u = fill_controlled(page,
                                   "() => document.getElementById('%s')" % fields2["tid"],
                                   u) if fields2.get("tid") else False
            ok_p = fill_controlled(page,
                                   "() => document.getElementById('%s')" % fields2["pid"],
                                   p) if fields2.get("pid") else False
            return bool(ok_u and ok_p)
    except Exception:
        pass
    return False


def submit(page) -> bool:
    try:
        loc = page.locator("#btn_login").first
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=5000)
        return True
    except Exception:
        return False


def wait_result(page, seconds, log) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            url = page.url or ""
            st = page.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              return {logged:/退出登录|个人中心|欢迎您|安全退出/.test(b),
                      badcred:/账号或密码|密码错误|用户不存在/.test(b),
                      captcha:!!document.querySelector('.geetest_panel_box,.geetest_window,.geetest_holder')};
            }""")
        except Exception:
            time.sleep(2)
            continue
        if st.get("logged"):
            return "ok"
        if st.get("badcred"):
            return "badcred"
        if "shiming" not in url:
            return "ok(跳回)"
        time.sleep(2)
    return "timeout"


def main() -> int:
    u, p = creds()
    log("凭据：%s / %s" % (u[:3] + "****" + u[-4:] if len(u) >= 7 else "未配置",
                           "已配置" if p else "未配置"))
    if not u or not p:
        log("⚠ 请先在软件「账号密码」里配置 gsxt 账号")
        return 1

    bs = BrowserSession("Edge", log=log, timeout=30)
    pw, browser, ctx, page = bs.open()
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
        log("已到登录页")
        time.sleep(1.2)
        log("=== 3) 自动填账号密码（逐字符）+ 提交 ===")
        if not fill_creds(landed, u, p):
            log("填值失败")
            return 1
        log("填值 OK，2 秒后提交…")
        time.sleep(2.0)
        if not submit(landed):
            log("提交失败")
            return 1
        log("已提交，等待结果（若弹极验请在浏览器窗口里完成滑块/点选）…")
        r1 = wait_result(landed, 30, log)
        log("阶段一：%s" % r1)
        if r1 != "ok" and r1 != "ok(跳回)":
            log(">>> 请现在在浏览器窗口里完成极验验证码 <<<")
            log("（60 秒内完成会自动继续）")
            r2 = wait_result(landed, 60, log)
            log("阶段二（人工过码后）：%s" % r2)
            r1 = r2
        if r1 != "ok" and r1 != "ok(跳回)":
            log("登录未成功，结束")
            return 1
        log("✔ 登录成功")
        log("=== 4) 回首页 → 查询 ===")
        time.sleep(2.0)
        res2 = nav.goto_via_landing(page, "gsxt", log=lambda *a, **k: None,
                                    timeout_ms=45000)
        lp = res2.get("page") or page
        if not res2.get("ok"):
            log("登录后回首页失败")
            return 1
        st = lp.evaluate("""()=>{
          const b=(document.body&&document.body.innerText)||'';
          return {logged:/退出登录|个人中心|欢迎您|安全退出/.test(b)};
        }""")
        log("首页登录态=%s" % st.get("logged"))
        if not fill_controlled(lp, "() => document.getElementById('keyword')",
                               COMPANY):
            log("填词失败")
            return 1
        time.sleep(0.8)
        try:
            loc = lp.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            log("点击：TRUSTED_CLICK")
        except Exception as exc:
            log("点击失败:%s" % str(exc)[:50])
            return 1
        deadline = time.time() + 16
        verdict = "✘ 无反应"
        while time.time() < deadline:
            try:
                r = lp.evaluate("""()=>{
                  const sel='.geetest_panel_box,.geetest_window,.geetest_holder';
                  const e=document.querySelector(sel);
                  let vis=false;
                  if(e){const b=e.getBoundingClientRect();
                        const s=getComputedStyle(e);
                        vis=b.width>50&&b.height>40
                           &&s.display!=='none'&&s.visibility!=='hidden';}
                  return {listing:/corp-query-search/.test(location.href), vis:vis};
                }""")
            except Exception:
                r = {}
            if r.get("listing"):
                verdict = "✔ 跳到结果页（放行！）"
                break
            if r.get("vis"):
                verdict = "✔ 极验弹出（放行！）"
                break
            time.sleep(2)
        log("查询判定：%s" % verdict)
        log("")
        log("=== 最终结论 ===")
        log("登录后查询：%s" % verdict)
        return 0
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
