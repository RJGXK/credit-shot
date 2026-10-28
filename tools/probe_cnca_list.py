# -*- coding: utf-8 -*-
"""CNCA「认证结果综合查询」页（skipResultList）真机 DOM 探查。

背景：点【查询】后站点**整页跳转**到
    https://cx.cnca.cn/CertECloud/result/skipResultList?certNumber=&orgName=xxx&fromIndex=true
组织列表是在这个新页面上渲染的（不是首页 AJAX）。

本脚本做三件事：
  1. 直接打开该 URL（带 orgName），dump 页面结构（类名/表结构/关键容器）；
  2. 把页面上的 JS 源码抓下来（认证结果页的渲染逻辑）；
  3. 打印极验弹层相关元素，判断这一段是否也要人工。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)

COMPANY = "中瑞盛世（北京）建筑有限公司"
URL = ("https://cx.cnca.cn/CertECloud/result/skipResultList"
       "?certNumber=&orgName=%s&fromIndex=true"
       % "中瑞盛世（北京）建筑有限公司")


def dump_dom(page):
    info = page.evaluate("""()=>{
      const pick = (sel)=>document.querySelectorAll(sel).length;
      const cls = {};
      document.querySelectorAll('[class]').forEach(e=>{
        (e.className||'').split(/\\s+/).filter(Boolean).forEach(c=>{
          cls[c]=(cls[c]||0)+1;});
      });
      const tables=[...document.querySelectorAll('table')].map(t=>({
        id:t.id||'', cls:t.className||'',
        rows:t.rows?t.rows.length:0,
        head:[...t.querySelectorAll('th')].map(x=>(x.innerText||'').trim()).slice(0,12),
        firstRowCells:[...(t.rows&&t.rows[1]?t.rows[1].cells:[])].map(
          c=>{const i=c.querySelector('input');return {
            txt:(c.innerText||'').trim().slice(0,30),
            cid:c.id||'', ccls:c.className||'',
            inp:i?(i.name+'='+i.value):''};}),
      }));
      return {
        url:location.href,
        title:document.title,
        orgRowsClass:pick('[class^="orgInfoRow"]'),
        orgRowsId:pick('[id^="orgInfoRow"]'),
        certCards:pick('.certInfoSingle'),
        certInfoId:pick('[id^="certInfo"]'),
        orgContent:pick('.orgContent'),
        certContent:pick('.certContent'),
        hasGeetest:pick('[class*=geetest]'),
        bodyText:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,600),
        tables:tables,
        topClasses:Object.entries(cls).sort((a,b)=>b[1]-a[1]).slice(0,45),
      };
    }""")
    print("\n===== DOM 结构 =====")
    print(json.dumps(info, ensure_ascii=False, indent=1)[:6000])
    return info


def grab_js(page):
    """把页面上的 JS 源码抓下来。"""
    srcs = page.evaluate("""()=>[...document.querySelectorAll('script[src]')]
      .map(s=>s.src).filter(Boolean)""")
    print("\n===== 页面 JS =====")
    for s in srcs:
        print("  ", s)
    out = {}
    for s in srcs:
        try:
            r = page.evaluate("""async (u)=>{
              const t = await fetch(u).then(r=>r.text());
              return t;
            }""", s)
        except Exception as exc:
            print("   抓取失败", s, exc)
            continue
        if r and len(r) > 500:
            name = os.path.basename(s.split("?")[0]) or "x.js"
            with open(os.path.join(OUT, "js_" + name), "w",
                      encoding="utf-8") as f:
                f.write(r)
            out[name] = len(r)
    print("  已保存:", out)
    return out


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        dump_dom(page)
        grab_js(page)
        page.screenshot(path=os.path.join(OUT, "skiplist.png"), full_page=True)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
