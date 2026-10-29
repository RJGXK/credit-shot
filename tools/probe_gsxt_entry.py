# -*- coding: utf-8 -*-
"""临时探针：验证 gsxt 的「搜索引擎进站 + 点查询」链路是否真能走通。

    python tools/probe_gsxt_entry.py

只做：
  1) 走 nav.goto_via_landing("gsxt")（现在是 Bing 搜索 → 点结果）
  2) 打印落地 URL / 是否有 #keyword / 是否有拒绝页文案
  3) 填企业名 → 真实点击【查询】→ 8 秒内看是否跳转 / 弹极验 / 被拒
不做：登录、选企业、截图。跑完自己关浏览器。
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import nav                      # noqa: E402
from core.browser import BrowserSession   # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    company = "北京百度网讯科技有限公司"
    bs = BrowserSession("Edge", log=log, timeout=30)
    bs.open()
    page = None
    for p in bs.ctx.pages:
        if "about:blank" in (p.url or "") or not (p.url or ""):
            page = p
            break
    if page is None:
        page = bs.ctx.pages[0] if bs.ctx.pages else bs.ctx.new_page()

    log("=== 1) 走入口链（Bing → 点结果）===")
    res = nav.goto_via_landing(page, "gsxt", log=log)
    log("入口结果：ok=%s via=%s reason=%s" % (res.get("ok"), res.get("via"),
                                             res.get("reason")))
    # 入口可能开新标签页：后续操作必须打在真正落地的那一页上
    page = res.get("page") or page

    def state() -> dict:
        try:
            return page.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              const el=document.getElementById('keyword');
              const r=el?el.getBoundingClientRect():null;
              return {url:location.href, title:document.title||'',
                      kw: !!(r&&r.width>0&&r.height>0),
                      blocked: /当前IP请求异常|可疑的攻击行为|更换IP地址|400 Bad Request/.test(b),
                      len:b.length,
                      head:b.replace(/\\s+/g,' ').slice(0,120)};
            }""")
        except Exception as exc:
            return {"err": str(exc)[:80]}

    st = state()
    log("落地：url=%s" % str(st.get("url"))[:90])
    log("      title=%s len=%s 有搜索框=%s 被拒=%s"
        % (st.get("title"), st.get("len"), st.get("kw"), st.get("blocked")))
    if st.get("head"):
        log("      正文：%s" % st["head"])

    # 监听控制台/页面错误：极验加载失败、站点脚本异常常在这里露出
    console_lines = []
    def on_console(msg):
        txt = (msg.text or "")
        if any(k in txt for k in ("geetest", "captcha", "验证", "error", "Error",
                                  "异常", "fail", "Fail", "failcode", "forbidden")):
            console_lines.append("[%s] %s" % (msg.type, txt[:180]))
    def on_error(err):
        console_lines.append("[pageerror] %s" % str(err)[:180])
    try:
        page.on("console", on_console)
        page.on("pageerror", on_error)
    except Exception:
        pass

    log("=== 2) 填企业名 + 真实点击【查询】===")
    try:
        page.wait_for_function("()=>document.readyState==='complete'", timeout=15000)
    except Exception:
        pass
    ok_fill = page.evaluate("""(name)=>{
      const el=document.getElementById('keyword');
      if(!el) return 'NO_INPUT';
      const proto=HTMLInputElement.prototype;
      const set=Object.getOwnPropertyDescriptor(proto,'value').set;
      el.focus(); set.call(el,name);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return el.value===name ? 'OK' : ('VALUE:'+el.value);
    }""", company)
    log("填词：%s" % ok_fill)

    clicked = "NONE"
    try:
        loc = page.locator("#btn_query").first
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=5000)
        clicked = "TRUSTED_CLICK"
    except Exception as exc:
        clicked = "FAIL:%s" % str(exc).splitlines()[0][:60]
    log("点击：%s" % clicked)

    def frame_states():
        """每个 frame 里极验占位/可见数量 + 正文长度。极验弹层常在独立 iframe。"""
        try:
            frames = list(page.frames)
        except Exception:
            frames = [page]
        out = []
        for idx, fr in enumerate(frames):
            try:
                r = fr.evaluate("""()=>{
                  const sel='.geetest_holder,.geetest_panel,.geetest_window,.geetest_wind,'
                          +'[id*=geetest],[class*=geetest],#popup-captcha,.gt_holder,.gt_popup';
                  const els=[...document.querySelectorAll(sel)];
                  const vis=els.filter(e=>{
                    try{const s=getComputedStyle(e);
                        if(s.display==='none'||s.visibility==='hidden'||+s.opacity===0) return false;
                    }catch(err){return false;}
                    const b=e.getBoundingClientRect();
                    return b.width>50&&b.height>40;
                  }).length;
                  return {n:els.length, vis:vis,
                          body:(document.body&&document.body.innerText||'').length};
                }""")
            except Exception as exc:
                r = {"err": str(exc)[:60]}
            out.append((idx, r))
        return out

    log("=== 3) 点查询后反应时间线（每 2 秒）===")
    log("   格式: url | frames=帧号:n占位/vis可见 | 反应")
    deadline = time.time() + 18
    last_reacted = ""
    while time.time() < deadline:
        try:
            r = page.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              return {url:location.href,
                      listing:/corp-query-search/.test(location.href),
                      blocked:/当前IP请求异常|可疑的攻击行为|400 Bad Request/.test(b)};
            }""")
        except Exception as exc:
            r = {"err": str(exc)[:60]}
        fs = frame_states()
        reacted = ""
        if r.get("listing"):
            reacted = "跳到结果页"
        elif any((f.get("vis") if isinstance(f, dict) else 0)
                 for _, f in fs if isinstance(f, dict)):
            reacted = "极验可见(iframe)"
        elif r.get("blocked"):
            reacted = "被拒"
        t = time.strftime("%H:%M:%S")
        log("[%s] %s | frames=%s | %s" % (
            t, str(r.get("url"))[:64],
            ";".join("%d:n%s/vis%s" % (i, f.get("n"), f.get("vis"))
                     for i, f in fs if isinstance(f, dict)),
            reacted or "无反应"))
        if reacted and "无反应" not in reacted and reacted != last_reacted:
            log("  >>> 有反应：%s" % reacted)
        last_reacted = reacted
        if reacted.startswith("跳到结果页") or reacted.startswith("极验可见"):
            break
        time.sleep(2.0)
    if console_lines:
        log("=== 控制台/错误（筛选）===")
        for line in console_lines[:30]:
            log("  %s" % line)
    else:
        log("（无相关控制台错误）")
    log("查询反应：%s" % (last_reacted or "18 秒内没有任何反应"))

    log("=== 结束（3 秒后关闭浏览器）===")
    time.sleep(3)
    try:
        bs.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
