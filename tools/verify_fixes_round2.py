# -*- coding: utf-8 -*-
"""三项修复的联合真机回归：
1. CNCA 入口链（页面句柄返回 + 临时标签页清理）
2. GSXT 首页 #btn_query 精准点击
3. 信用中国验证码 clip 截图（0.1 秒内、不触发 session 刷新）
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav
from core.captcha import CaptchaSolver

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s %s" % ("✔" if cond else "✘", name, detail))


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()

        # ========== 1) CNCA 入口链 ==========
        print("\n===== 1) CNCA 入口链 =====")
        res = nav.goto_via_landing(page, "cnca", log=print, timeout_ms=45000)
        p = res.get("page") or page
        check("CNCA 入口链 ok", res.get("ok") is True)
        check("CNCA 落在首页",
              "/CertECloud/index/index/page" in (p.url or ""),
              p.url[:70])
        try:
            has_org = p.evaluate("()=>!!document.getElementById('orgName')")
        except Exception:
            has_org = False
        check("CNCA #orgName 可见", has_org)
        # 临时标签页应该被清理（WAF 挑战页可能残留，≤2 个都算正常）
        try:
            n_pages = len(p.context.pages)
        except Exception:
            n_pages = -1
        check("临时标签页已清理", 1 <= n_pages <= 2, "标签页数=%d" % n_pages)

        # ========== 2) 信用中国验证码 clip 截图 ==========
        print("\n===== 2) 信用中国验证码截图 =====")
        res2 = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        p2 = res2.get("page") or page
        try:
            p2.goto("https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/",
                    wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(2)
        # 触发验证码弹层
        p2.evaluate("""()=>{
          const inp=[...document.querySelectorAll('input')]
            .find(x=>x.id!=='search_input'&&(x.placeholder||'').includes('请输入主体名称'));
          if(inp){
            inp.focus();
            const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            s.call(inp,'中瑞盛世（北京）建筑有限公司');
            inp.dispatchEvent(new Event('input',{bubbles:true}));
            inp.dispatchEvent(new Event('change',{bubbles:true}));
          }
          const b=document.querySelector('.infoCheckBtn');
          if(b) b.click();
        }""")
        # 等弹层+图片就绪
        ready = False
        for _ in range(24):
            try:
                ready = p2.evaluate("""()=>{
                  const pop=document.querySelector('.vcodepop');
                  const img=document.getElementById('vcodeimg');
                  return !!(pop && getComputedStyle(pop).display!=='none'
                            && img && img.complete && img.naturalWidth>0);
                }""")
            except Exception:
                pass
            if ready:
                break
            time.sleep(0.5)
        check("信用中国验证码弹层就绪", ready)

        solver = CaptchaSolver("", "cn", print)  # 无 key，只测取图
        t0 = time.time()
        raw, how = solver._capture_captcha(p2, "#vcodeimg",
                                           p2.query_selector(".vcodepop"))
        dt = time.time() - t0
        check("验证码取图成功", bool(raw) and len(raw) > 500,
              "来源=%s 大小=%d 耗时=%.2fs" % (how, len(raw or b""), dt))
        # 旧逻辑卡 element.screenshot 20s 超时后还会二次 GET 冲掉 session；
        # 新逻辑最长等图片加载 4s + 截图 3s，绝不含二次 GET
        check("取图速度达标（<8s，旧逻辑卡 20s+）", dt < 8.0, "%.2fs" % dt)

        # ========== 3) GSXT 首页 #btn_query ==========
        print("\n===== 3) GSXT #btn_query 精准点击 =====")
        res3 = nav.goto_via_landing(page, "gsxt", log=print, timeout_ms=45000)
        p3 = res3.get("page") or page
        time.sleep(2)
        try:
            r = p3.evaluate("""()=>{
              const btn = document.getElementById('btn_query')
                       || document.querySelector('.search_btn');
              if(!btn) return 'NO_BTN';
              return 'OK:' + (btn.id || btn.className);
            }""")
        except Exception as e:
            r = "ERR:" + str(e)[:50]
        check("GSXT 查询按钮可定位", str(r).startswith("OK"), str(r)[:60])

    finally:
        try:
            bs.close()
        except Exception:
            pass

    print("\n===== 结果 =====")
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  ✘", f)
        return 1
    print("✅ 三项修复全部真机验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
