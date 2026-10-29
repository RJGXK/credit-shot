# -*- coding: utf-8 -*-
"""探针：查「信用中国验证码总是识别到上一个」。

要查清三件事：
1. 点「看不清? 换一张」之后，#vcodeimg 的 src / 元素身份 / 像素有没有变；
2. 站点在「验证码错误」后是**自己**换图还是**换 DOM 元素**（可能留下重复 id）；
3. 截图时到底截到的是哪张图（把每次截到的字节存成 png 肉眼对比）。

用法：python tools/probe_cc_stale.py [公司名]
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

INFO_JS = """
()=>{
  const all=[...document.querySelectorAll('img')].filter(i=>
      /vcode|captcha|verify|code/i.test((i.id||'')+' '+(i.className||'')+' '+(i.src||'')));
  return {
    count: document.querySelectorAll('#vcodeimg').length,
    imgs: all.map(i=>({id:i.id||'', cls:(i.className||'').toString().slice(0,30),
                        src:(i.currentSrc||i.src||'').slice(0,120),
                        nat:i.naturalWidth+'x'+i.naturalHeight,
                        complete:!!i.complete,
                        rect:(()=>{const b=i.getBoundingClientRect();
                             return Math.round(b.x)+','+Math.round(b.y)+','+
                                    Math.round(b.width)+'x'+Math.round(b.height);})(),
                        visible:!!i.offsetParent})),
    box: (()=>{const b=document.querySelector('.vcodeimgbox');
               return b?(b.innerText||'').replace(/\\s+/g,' ').slice(0,120):''})(),
    popHtml: (()=>{const p=document.querySelector('.vcodepop');
               return p?(p.innerHTML||'').slice(0,1200):''})(),
  };
}
"""


def shot_img(page, tag):
    """截 #vcodeimg 存盘，返回 (bytes, md5)。"""
    try:
        el = page.query_selector("#vcodeimg")
        if not el:
            return None, "-"
        raw = el.screenshot(timeout=8000)
    except Exception as exc:
        print("  截图异常:", exc)
        return None, "-"
    fn = os.path.join(OUT, "stale_%s.png" % tag)
    open(fn, "wb").write(raw)
    return raw, hashlib.md5(raw).hexdigest()[:10]


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    bs = BrowserSession("Edge", print, 30)
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")

        deadline = time.time() + 25
        while time.time() < deadline:
            st = page.evaluate("()=>{const p=document.querySelector('.vcodepop');"
                               "return !!(p&&getComputedStyle(p).display!=='none');}")
            if st:
                break
            time.sleep(1.0)
        time.sleep(2)

        info = page.evaluate(INFO_JS)
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2)[:3000])

        print("\n-- 第 1 次截图 --")
        raw1, h1 = shot_img(page, "1")
        print("  md5=%s size=%s" % (h1, len(raw1 or b"")))

        print("\n-- 点【看不清? 换一张】 --")
        page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                      " if(s) s.click(); else print('NO-SPAN');}")
        time.sleep(3)
        info2 = page.evaluate(INFO_JS)
        print(json.dumps(info2, ensure_ascii=False, indent=2)[:2000])
        raw2, h2 = shot_img(page, "2")
        print("  md5=%s size=%s  与第1次相同=%s" % (h2, len(raw2 or b""), h1 == h2))

        print("\n-- 再点一次换一张 --")
        page.evaluate("()=>{const s=document.querySelector('.vcodepop .vcodeimgbox span');"
                      " if(s) s.click();}")
        time.sleep(3)
        raw3, h3 = shot_img(page, "3")
        print("  md5=%s size=%s  与第2次相同=%s" % (h3, len(raw3 or b""), h2 == h3))

        # 再用「直接取字节」的路径对比一次（不刷新接口，只读当前 src）
        try:
            src = page.evaluate("()=>{const i=document.querySelector('#vcodeimg');"
                                "return i?(i.currentSrc||i.src||''):'';}")
            if src:
                resp = page.request.get(src, headers={
                    "Accept": "image/*,*/*;q=0.8",
                    "Referer": "https://www.creditchina.gov.cn/"})
                body = resp.body()
                print("\n  直接 GET 当前 src: status=%s ct=%s len=%s md5=%s"
                      % (resp.status, resp.headers.get("content-type"),
                         len(body), hashlib.md5(body).hexdigest()[:10]))
                open(os.path.join(OUT, "stale_api.png"), "wb").write(body)
        except Exception as exc:
            print("  直接 GET 失败:", exc)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
