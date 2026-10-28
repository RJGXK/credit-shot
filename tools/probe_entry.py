# -*- coding: utf-8 -*-
"""探测各站点的「进入路径」：直连 vs 经上级页面点击链接跳转。

输出每个方案的最终 URL / 标题 / 正文长度 / 关键元素是否存在，
并把页面截图存到 output_dir，便于人工核对是不是白页。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def state(page):
    try:
        return page.evaluate("""()=>({
          url: location.href,
          title: document.title || '',
          len: (document.body ? (document.body.innerText||'').length : 0),
          head: (document.body ? (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,180) : ''),
          keyword: !!document.getElementById('keyword'),
          iframeCount: document.querySelectorAll('iframe').length,
        })""")
    except Exception as exc:
        return {"url": page.url, "err": str(exc).splitlines()[0][:120]}


def probe(page, name, url, goto_url=None):
    """goto_url 为落地页；在落地页里找指向 url 的链接点击。"""
    print("\n===== %s =====" % name)
    try:
        if goto_url:
            page.goto(goto_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2.5)
            st0 = state(page)
            print("  落地页: %s | title=%s | len=%s"
                  % (st0.get("url", "")[:70], st0.get("title", "")[:30],
                     st0.get("len", "?")))
            clicked = page.evaluate("""(arg)=>{
              const host=arg.host;
              const as=[...document.querySelectorAll('a[href]')];
              const hit=as.find(a=>{try{return new URL(a.href,location.href).host===host;}catch(e){return false;}});
              if(!hit) return 'NO_LINK';
              hit.click();
              return 'CLICK:'+hit.href.slice(0,80);
            }""", {"host": host_of(url)})
            print("  点链接: %s" % clicked)
            if not str(clicked).startswith("CLICK"):
                print("  -> 落地页上没有指向该站的链接")
                return
            time.sleep(6)
        else:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                print("  goto 异常(不致命): %s" % str(exc).splitlines()[0][:110])
            time.sleep(4)
        st = state(page)
        print("  最终: %s | title=%s | len=%s | keyword=%s"
              % (str(st.get("url", ""))[:80], st.get("title", "")[:30],
                 st.get("len", "?"), st.get("keyword", "?")))
        print("  头部: %s" % str(st.get("head", ""))[:160])
        try:
            shot = os.path.join(OUT, "%s.png" % name)
            os.makedirs(OUT, exist_ok=True)
            page.screenshot(path=shot, full_page=False)
            print("  截图: %s" % shot)
        except Exception as exc:
            print("  截图失败: %s" % str(exc).splitlines()[0][:80])
    except Exception as exc:
        print("  方案异常: %s" % str(exc).splitlines()[0][:120])


def host_of(url):
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except Exception:
        return url


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        probe(page, "gsxt_直连", "https://www.gsxt.gov.cn/index.html")
        probe(page, "gsxt_经samr", "https://www.gsxt.gov.cn/index.html",
              goto_url="https://www.samr.gov.cn/")
        probe(page, "gsxt_经gov", "https://www.gsxt.gov.cn/index.html",
              goto_url="https://www.gov.cn/")
        probe(page, "gsxt_经信用中国", "https://www.gsxt.gov.cn/index.html",
              goto_url="https://www.creditchina.gov.cn/")
        probe(page, "ccgp_直连", "https://www.ccgp.gov.cn/")
        probe(page, "ccgp_经gov", "https://www.ccgp.gov.cn/",
              goto_url="https://www.gov.cn/")
        probe(page, "zxgk_直连", "https://zxgk.court.gov.cn/shixin/")
        probe(page, "plap_直连", "https://www.plap.mil.cn/freecms-glht/site/juncai/jdjc/index.html")
        probe(page, "mohurd_直连", "https://jzsc.mohurd.gov.cn/home")
        probe(page, "wenshu_直连", "https://wenshu.court.gov.cn/")
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
