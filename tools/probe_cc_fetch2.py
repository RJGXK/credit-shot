# -*- coding: utf-8 -*-
"""探针4（决定性）：信用中国验证码 —— 页面内 fetch 原始字节这条路能不能走通。

已确认的事实：
  · 图挂在跨域 public.creditchina.gov.cn；
  · Playwright 的 page.request.get(src) 会被站点回 412 + HTML（所以图变破图）；
  · **页面内 fetch(src, {credentials:'include'}) 能拿到 200 + image/jpeg 原始字节**；
  · canvas 因为跨域被污染，取不到像素。

本探针回答：
  Q1. 同一个 src 在页面内连 fetch 两次，返回的是同一张图吗？
      （相同 = URL 是令牌，自己取不会顶掉 session 里的验证码）
  Q2. 自己取到的图，和浏览器正在显示的那张，是同一张内容吗？
  Q3. 用**原始字节**（不是被浏览器拉伸过的截图）去识别，准确吗？
  Q4. 端到端：填入 -> 点【验证】-> 站点认不认？

用法：python tools/probe_cc_fetch2.py [公司名]
"""
import base64
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession          # noqa: E402
from core import nav                             # noqa: E402
from core.captcha import CaptchaSolver, preprocess_captcha  # noqa: E402
from auth.credentials import load_captcha_key    # noqa: E402

TARGET = "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")
os.makedirs(OUT, exist_ok=True)

FETCH_TWICE_JS = """
async (url)=>{
  const out={};
  const grab=async()=>{
    const r=await fetch(url,{credentials:'include',cache:'no-store'});
    const b=await r.blob();
    const buf=await b.arrayBuffer();
    let bin=''; const u8=new Uint8Array(buf);
    for(let i=0;i<u8.length;i++) bin+=String.fromCharCode(u8[i]);
    return {status:r.status, ct:r.headers.get('content-type'),
            size:b.size, b64:btoa(bin)};
  };
  try{ out.one=await grab(); }catch(e){ out.err1=String(e); }
  try{ out.two=await grab(); }catch(e){ out.err2=String(e); }
  return out;
}
"""


def md5(b):
    return hashlib.md5(b or b"").hexdigest()[:10]


def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "中瑞盛世（北京）建筑有限公司"
    key = load_captcha_key()
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        res = nav.goto_via_landing(page, "creditchina", log=print, timeout_ms=45000)
        if res.get("page") is not None:
            page = res["page"]
        nav.goto(page, TARGET, timeout_ms=45000, log=print)
        time.sleep(4)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称')"
                  " && x.id !== 'search_input')")
        el = page.evaluate_handle(finder).as_element()
        if el is not None:
            el.evaluate("e => { e.focus(); e.select(); }")
            page.keyboard.insert_text(company)
            time.sleep(0.6)
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn');"
                      " if(b) b.click();}")
        deadline = time.time() + 25
        while time.time() < deadline:
            shown = page.evaluate("()=>{const p=document.querySelector('.vcodepop');"
                                  "return !!(p&&getComputedStyle(p).display!=='none');}")
            if shown:
                break
            time.sleep(1.0)
        time.sleep(3)

        info = page.evaluate(
            """()=>{const i=document.querySelector('#vcodeimg');
                 return {src:(i&&(i.currentSrc||i.src))||'',
                         nat:i?((i.naturalWidth||0)+'x'+(i.naturalHeight||0)):''};}""")
        print("\n页面上的图：%s" % info)
        src = info["src"]
        if not src:
            print("没有 src")
            return

        print("\n===== Q1/Q2 页面内 fetch 同一 src 两次 =====")
        out = page.evaluate(FETCH_TWICE_JS, src)
        b1 = b2 = b""
        if out.get("one"):
            b1 = base64.b64decode(out["one"]["b64"])
            print("  第1次: status=%s ct=%s len=%d md5=%s"
                  % (out["one"]["status"], out["one"]["ct"], len(b1), md5(b1)))
        if out.get("two"):
            b2 = base64.b64decode(out["two"]["b64"])
            print("  第2次: status=%s ct=%s len=%d md5=%s"
                  % (out["two"]["status"], out["two"]["ct"], len(b2), md5(b2)))
        if b1 and b2:
            print("  → 两次%s" % ("相同（URL 是令牌，自己取安全）" if b1 == b2
                                  else "不同（每次请求都会换验证码，不能自己取）"))
        if b1:
            open(os.path.join(OUT, "fetch2_orig.jpg"), "wb").write(b1)

        # 和页面显示的图比（把截图缩到原图尺寸比像素）
        solver = CaptchaSolver(key, "cn", print)
        scope = page.query_selector(".vcodepop")
        shot, how, meta = solver._capture_captcha(page, "#vcodeimg", scope, ".vcodepop")
        if shot and b1:
            from PIL import Image
            import io as _io
            a = Image.open(_io.BytesIO(shot)).convert("L")
            c = Image.open(_io.BytesIO(b1)).convert("L")
            print("  截图 %s / 原图 %s" % (a.size, c.size))
            if a.size != c.size:
                a = a.resize(c.size, Image.LANCZOS)
            diff = sum(abs(x - y) for x, y in zip(a.getdata(), c.getdata()))
            print("  → 平均像素差 %.1f（<20 视为同一张）"
                  % (diff / max(1, c.size[0] * c.size[1])))

        # Q3: 用原始字节识别
        if b1:
            client = solver.client()
            for name, data in (("原始字节", b1),
                               ("原始字节+预处理", preprocess_captcha(b1))):
                try:
                    txt = client.solve_image_to_text(data)
                except Exception as exc:
                    txt = "ERR:%s" % exc
                print("  识别(%s) -> %r" % (name, txt))

            # Q4: 端到端 —— 填入 -> 验证
            txt = client.solve_image_to_text(preprocess_captcha(b1))
            if not txt or txt.startswith("ERR"):
                print("  识别失败，跳过端到端")
                return
            ok = solver._fill_captcha_input(page, ".vcodepop", txt)
            print("  填入 %r -> %s" % (txt, ok))
            page.evaluate("()=>{const b=document.querySelector('.vcodepop a.confirm');"
                          " if(b) b.click();}")
            time.sleep(3)
            st = page.evaluate(
                """()=>{const p=document.querySelector('.vcodepop');
                     const e=document.querySelector('.vcodepop .errortip');
                     return {pop: p?getComputedStyle(p).display:'',
                             err: e?(e.innerText||'').trim():'',
                             cookie:(document.cookie||'').includes('vcode=1')};}""")
            print("  端到端结果：弹层=%s 错误提示=%r cookie=%s"
                  % (st.get("pop"), st.get("err"), st.get("cookie")))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
