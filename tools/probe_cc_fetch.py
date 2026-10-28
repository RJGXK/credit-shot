# -*- coding: utf-8 -*-
"""探针：验证码图片被 ORB 拦掉时，还有哪些办法能拿到图片字节。

依次试：
 A. <img> 自然加载（naturalWidth>0）
 B. 页面内 fetch(url, {credentials:'include'})  -> blob -> base64
 C. 页面内 new Image(crossOrigin='anonymous') + canvas -> dataURL
 D. Playwright APIRequestContext page.request.get(url)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession
from core import nav

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_out")
os.makedirs(OUT, exist_ok=True)

FETCH_JS = """
(url)=>{
  return (async ()=>{
    const out={};
    // B) fetch
    try{
      const r=await fetch(url,{credentials:'include'});
      out.fetchStatus=r.status;
      out.fetchCT=r.headers.get('content-type');
      out.fetchACAO=r.headers.get('access-control-allow-origin');
      const b=await r.blob();
      out.fetchSize=b.size;
      out.fetchType=b.type;
    }catch(e){ out.fetchErr=String(e); }
    // C) canvas
    try{
      const img=new Image();
      img.crossOrigin='anonymous';
      img.src=url;
      await img.decode();
      const c=document.createElement('canvas');
      c.width=img.naturalWidth; c.height=img.naturalHeight;
      c.getContext('2d').drawImage(img,0,0);
      out.canvasData=c.toDataURL('image/png');
      out.canvasSize=out.canvasData.length;
    }catch(e){ out.canvasErr=String(e); }
    return out;
  })();
}
"""


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
        time.sleep(5)

        src = page.evaluate("()=>{const i=document.querySelector('#vcodeimg'); return i?i.src:'';}")
        nat = page.evaluate("()=>{const i=document.querySelector('#vcodeimg');"
                             " return i?(i.naturalWidth+'x'+i.naturalHeight):'-';}")
        print("A) img natural =", nat)
        print("   src =", src[:100])

        print("\nB/C) 页面内 fetch + canvas …")
        try:
            out = page.evaluate(FETCH_JS, src)
        except Exception as exc:
            out = {"evalErr": str(exc)}
        for k, v in out.items():
            if k == "canvasData":
                print("   %s = <len %s>" % (k, len(v)))
                import base64
                b64 = v.split(",", 1)[1]
                open(os.path.join(OUT, "cc_canvas.png"), "wb").write(base64.b64decode(b64))
            else:
                print("   %s = %r" % (k, v))

        print("\nD) APIRequestContext …")
        try:
            resp = page.request.get(src)
            body = resp.body()
            print("   status=%s ct=%s len=%d head=%r"
                  % (resp.status, resp.headers.get("content-type"), len(body), body[:12]))
        except Exception as exc:
            print("   异常:", exc)
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
