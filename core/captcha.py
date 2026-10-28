# -*- coding: utf-8 -*-
"""core/captcha.py —— 验证码处理（引擎侧）。

策略：
  * 配了打码服务 API Key 且题型支持 -> 全自动（识别 -> 填入 -> 提交 -> 判错 -> 换图重试）；
  * 没配 Key 或题型不支持            -> 回落人工，程序只把人带到验证码处。

实战踩过的坑（都已在下面代码里处理）
--------------------------------
1. **只换验证码图，不要刷新整页**：站点的「看不清? 换一张」是换图动作，
   刷新整页会把已经填好的主体名称、弹层状态全部冲掉。
2. **点对了提交按钮**：按文字模糊匹配会先命中包住按钮的容器 div
   （div.buttongroup 的 innerText 也含「验证」），点它等于没点。
   这里改成「优先精确选择器 + 只挑最内层元素」。
3. **图片可能被浏览器拦掉**：信用中国的验证码挂在 public.creditchina.gov.cn，
   跨源 <img> 会被 Edge 的 ORB（Opaque Response Blocking）拦成
   net::ERR_BLOCKED_BY_ORB —— 图**根本不显示**（naturalWidth=0），
   用户看到的是「坏图」。这时改用 APIRequestContext 取原始字节。
4. **识别错了要能重试**：提交后站点会提示「验证码错误」并自动换图，
   程序要能「换图 -> 重新识别 -> 再提交」，而不是一次就放弃。

YesCaptcha 协议客户端在 core/yescaptcha.py。
"""
from __future__ import annotations

import io
import time

from core.yescaptcha import YesCaptcha

__all__ = ["CaptchaSolver", "image_looks_blank", "denoise_captcha",
           "preprocess_captcha", "image_not_loaded"]


def image_looks_blank(data: bytes) -> bool:
    """判断一张验证码截图是不是「白板」。

    实测坑：有些平台的验证码图片**第一次加载出来是空白**，
    点一下「换一张 / 刷新」才会真正出图。
    这时送去打码服务，识别结果就是空内容（用户反馈的
    「识别出来无内容」）。

    判定：灰度图的标准差极小（几乎纯色）→ 认为是白板。
    """
    try:
        from PIL import Image, ImageStat
        img = Image.open(io.BytesIO(data)).convert("L")
        stat = ImageStat.Stat(img)
        return float(stat.stddev[0]) < 8.0
    except Exception:
        return False


def image_not_loaded(target, selector: str) -> bool:
    """判断页面上的验证码图片**有没有真正加载出来**。

    实测坑（信用中国）：验证码图挂在 public.creditchina.gov.cn，
    跨源 <img> 请求会被 Edge 的 ORB 拦掉：
        net::ERR_BLOCKED_BY_ORB
    页面上 img.complete=true 但 naturalWidth=0 —— 用户看到的是「坏图」，
    送去打码服务只能识别出一堆乱码。
    这时要用 APIRequestContext 重新取字节（见 CaptchaSolver.fetch_image_bytes）。

    返回 True 表示「没加载出来 / 加载坏了」。
    """
    js = """
    (sel)=>{
      const e=document.querySelector(sel);
      if(!e) return true;              // 压根没有图
      return !(e.complete && e.naturalWidth>0);
    }
    """
    try:
        r = target.evaluate(js, selector)
    except Exception:
        return True
    return bool(r)


def denoise_captcha(data: bytes, dilate: int = 1, thr: int = 150):
    """去掉图形验证码里的干扰线，返回清理后的 PNG 字节。

    干扰线是 1px 宽的斜线/曲线；字符笔画在水平或垂直方向上至少有 3px 连通。
    判据：像素若处在「长度>=3 的水平段」或「长度>=3 的垂直段」里就算笔画；
    再把掩码膨胀 1px，把贴着笔画的斜线段（如 Z 的斜杠）补回来。

    只用 Pillow + 纯 Python，不引入新依赖（打包版依赖固定三个库）。
    """
    try:
        from PIL import Image, ImageFilter
    except Exception:
        return data
    try:
        im = Image.open(io.BytesIO(data)).convert("L")
        w, h = im.size
        if w * h > 400000:              # 太大了就别折腾了
            return data
        px = im.load()
        dark = [[1 if px[x, y] < thr else 0 for x in range(w)] for y in range(h)]
        keep = [[0] * w for _ in range(h)]
        for y in range(h):
            row = dark[y]
            for x in range(w):
                if not row[x]:
                    continue
                a = x
                while a - 1 >= 0 and row[a - 1]:
                    a -= 1
                b = x
                while b + 1 < w and row[b + 1]:
                    b += 1
                if b - a + 1 >= 3:
                    keep[y][x] = 1
                    continue
                c = y
                while c - 1 >= 0 and dark[c - 1][x]:
                    c -= 1
                d = y
                while d + 1 < h and dark[d + 1][x]:
                    d += 1
                if d - c + 1 >= 3:
                    keep[y][x] = 1
        mask = Image.new("L", (w, h), 0)
        mp = mask.load()
        for y in range(h):
            ky = keep[y]
            for x in range(w):
                if ky[x]:
                    mp[x, y] = 255
        if dilate:
            mask = mask.filter(ImageFilter.MaxFilter(3))
        black = Image.new("L", (w, h), 0)
        white = Image.new("L", (w, h), 255)
        clean = Image.composite(black, white, mask)
        buf = io.BytesIO()
        clean.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return data


def preprocess_captcha(data: bytes, scale: int = 2, denoise: bool = False) -> bytes:
    """验证码送识别前的预处理：适度放大，保留彩色笔画。

    注意：现代 OCR / 打码模型对彩色原图的特征识别率最高，
    粗暴二值化（denoise）会把彩色浅色笔画冲掉，导致识别率暴跌甚至误报。
    因此默认 denoise=False，仅做适度平滑放大（scale=2）。
    """
    try:
        from PIL import Image
    except Exception:
        return data
    try:
        cur = denoise_captcha(data) if denoise else data
        im = Image.open(io.BytesIO(cur))
        if scale and scale > 1 and im.width < 300:
            im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return data


def _click_refresh(target, log, scope: str = "", nap=None) -> bool:
    """点验证码上的「刷新 / 换一张」——**只换图，绝不刷新整个页面**。

    常见做法有四种，按顺序尝试：
      1. 站点自己的换图控件（.vcodeimgbox span「看不清? 换一张」/ .geetest_refresh …）；
      2. 文字里带「换一张 / 看不清 / 刷新 / 换一」的可点元素；
      3. 直接点验证码图片本身（很多站点点图即换图）；
      4. 改 img.src 加时间戳强制重载（最后手段，仍然只换图）。

    scope：限定在某个容器内找（信用中国的换图文字就在 .vcodepop 里）。
    """
    js = """
    (arg)=>{
      const root = arg.scope ? document.querySelector(arg.scope) : document;
      if(!root) return 'NONE';
      const cands=[
        '.vcodeimgbox span','.vcodeimgbox a','.vcodeimgbox em',
        '.geetest_refresh','.geetest_slider_refresh','[class*="refresh"]',
        '[id*="refresh"]','[title*="刷新"]','[title*="换一"]',
        'a[href*="captcha"]','span[onclick*="captcha"]','span[onclick*="code"]',
        'em[onclick*="code"]'
      ];
      const usable=e=>{
        const b=e.getBoundingClientRect();
        return b.width>=4 && b.height>=4;
      };
      for(const sel of cands){
        const els=[...root.querySelectorAll(sel)];
        for(const e of els){
          if(!usable(e)) continue;
          const tag=e.tagName;
          const txt=(e.innerText||e.title||'').replace(/\\s+/g,'');
          if(tag==='IMG'){ e.click(); return 'CLICK_IMG:'+sel; }
          if(sel.indexOf('onclick')>=0 || sel.indexOf('href')>=0 ||
             /刷新|换一|换张|看不清/.test(txt) || sel.indexOf('vcode')>=0 ||
             sel.indexOf('geetest')>=0 || sel.indexOf('refresh')>=0){
            e.click(); return 'CLICK:'+sel;
          }
        }
      }
      // 兜底：文字里写着「换一张 / 看不清 / 刷新」的元素
      const hits=[...root.querySelectorAll('a,span,em,i,div,button')].filter(e=>{
        const t=(e.innerText||'').replace(/\\s+/g,'');
        return /换一张|看不清|刷新验证码|换图|重新获取/.test(t) && e.children.length===0;
      });
      if(hits.length){ hits[0].click(); return 'CLICK_TEXT:'+(hits[0].innerText||'').slice(0,12); }
      return 'NONE';
    }
    """
    try:
        r = target.evaluate(js, {"scope": scope})
    except Exception:
        return False
    if str(r).startswith("CLICK"):
        log("  ↻ 已刷新验证码（%s）" % str(r)[6:34])
        (nap or time.sleep)(1.2)
        return True
    return False


def _reload_image(target, selector: str, nap=None) -> bool:
    """给验证码图片加时间戳强制重载（图片不随刷新按钮变化时用）。"""
    js = """
    (sel)=>{
      const e=document.querySelector(sel);
      if(!e) return false;
      const base=(e.src||'').split('?')[0];
      e.src=base+'?_t='+Date.now();
      return true;
    }
    """
    try:
        ok = target.evaluate(js, selector)
    except Exception:
        return False
    if ok:
        (nap or time.sleep)(1.0)
        return True
    return False


class CaptchaSolver:
    """封装「能不能自动过验证码」这件事。"""

    def __init__(self, api_key: str = "", region: str = "cn", log=print,
                 should_stop=None):
        self.api_key = (api_key or "").strip()
        self.region = region if region in ("cn", "intl") else "cn"
        self.log = log
        # 可中断等待回调：引擎注入 check_stop，
        # 让验证码重试循环里也能响应【中止】/【跳过此步】。
        self.should_stop = should_stop
        self._client = None

    def nap(self, seconds: float) -> None:
        """可被中止/跳过的等待（无引擎注入时退化为普通 sleep）。"""
        should_stop = getattr(self, "should_stop", None)
        if should_stop is None:
            time.sleep(seconds)
            return
        # 每 0.2 秒探一次信号：引擎的 check_stop 会抛 Aborted/Skipped
        deadline = time.time() + max(0.0, float(seconds))
        while True:
            should_stop()
            left = deadline - time.time()
            if left <= 0:
                return
            time.sleep(min(0.2, left))

    @property
    def enabled(self) -> bool:
        """是否配置了打码服务。"""
        return bool(self.api_key)

    def client(self):
        """返回打码服务客户端；没配 API Key 返回 None（全部回落人工）。"""
        if not self.api_key:
            return None
        if self._client is None:
            try:
                self._client = YesCaptcha(
                    self.api_key, self.region, self.log)
            except Exception as exc:
                self.log("  ⚠ 打码服务初始化失败：%s" % exc)
                return None
        return self._client


    def fetch_image_bytes(self, page, src: str, referer: str = "") -> bytes:
        """用 APIRequestContext 取验证码图片的**原始字节**。

        为什么需要它：信用中国的验证码挂在 public.creditchina.gov.cn，
        跨源 <img> 请求被 Edge 的 ORB 拦掉（net::ERR_BLOCKED_BY_ORB），
        页面上的图是「坏图」（naturalWidth=0）。
        APIRequestContext 走同一套 Cookie、但不是浏览器渲染管线，能拿到真图。

        返回空字节表示取不到（调用方回落刷新/人工）。
        """
        if not src:
            return b""
        try:
            headers = {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
            if referer:
                headers["Referer"] = referer
            resp = page.request.get(src, headers=headers, timeout=30000)
            body = resp.body()
            ct = (resp.headers.get("content-type") or "").lower()
            if int(resp.status) == 200 and ("image" in ct
                                            or body[:2] in (b"\xff\xd8", b"\x89P")
                                            or body[:6] in (b"GIF87a", b"GIF89a")):
                return body
        except Exception as exc:
            self.log("  ⚠ 直接取验证码图片失败：%s" % str(exc).splitlines()[0][:70])
        return b""

    def _capture_captcha(self, page, img_selector: str, scope):
        """拿到当前验证码图片的字节。

        多层稳固截取策略：
        1. 确保图片已在浏览器中完成渲染（complete && naturalWidth > 0）；
        2. 针对带 CSS transform / fixed 的弹层，临时消除平移干扰，
           使 element.screenshot 0.1 秒内瞬间完成，杜绝 scroll-into-view 超时；
        3. 若 element.screenshot 异常，无缝降级到视口绝对坐标切片（page.screenshot clip）；
        4. 严禁对动态生成的验证码接口盲目发起 page.request.get(src)，避免服务端刷新 session
           导致页面中的验证码作废。
        """
        # 1. 等待图片真实加载就绪（最多等 4 秒）
        deadline = time.time() + 4.0
        while time.time() < deadline:
            ready = False
            try:
                ready = page.evaluate("""(sel)=>{
                  const el = document.querySelector(sel);
                  return !!(el && el.complete && (el.naturalWidth > 0 || el.offsetWidth > 0));
                }""", img_selector)
            except Exception:
                pass
            if ready:
                break
            self.nap(0.2)

        # 2. 临时消除弹窗父级 transform 动画与滚动干扰
        js_normalize = """(sel)=>{
          const img = document.querySelector(sel);
          if(!img) return null;
          let p = img.parentElement;
          let changed = [];
          while(p && p !== document.body && p !== document.documentElement){
            const st = window.getComputedStyle(p);
            if(st.transform && st.transform !== 'none'){
              const r = p.getBoundingClientRect();
              changed.push({
                el: p,
                oldTrans: p.style.transform,
                oldLeft: p.style.left,
                oldTop: p.style.top
              });
              p.style.transform = 'none';
              p.style.left = r.left + 'px';
              p.style.top = r.top + 'px';
            }
            p = p.parentElement;
          }
          const rect = img.getBoundingClientRect();
          window.__csRestores = changed;
          return {x: Math.round(rect.x), y: Math.round(rect.y),
                  width: Math.round(rect.width), height: Math.round(rect.height)};
        }"""
        js_restore = """()=>{
          if(window.__csRestores){
            for(const item of window.__csRestores){
              try{
                item.el.style.transform = item.oldTrans;
                item.el.style.left = item.oldLeft;
                item.el.style.top = item.oldTop;
              }catch(e){}
            }
            delete window.__csRestores;
          }
        }"""

        rect = None
        try:
            rect = page.evaluate(js_normalize, img_selector)
        except Exception:
            rect = None

        raw = None
        try:
            img = (scope.query_selector(img_selector) if scope
                   else page.query_selector(img_selector))
            if img:
                try:
                    raw = img.screenshot(timeout=3000)
                except Exception:
                    pass
            # 降级到 page clip 截图
            if not raw and rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                try:
                    raw = page.screenshot(clip=rect, timeout=3000)
                except Exception:
                    pass
        finally:
            try:
                page.evaluate(js_restore)
            except Exception:
                pass

        if raw:
            return raw, "页面图片"

        # 仅在非动态验证码（或确实没有任何方式截到图）时，才尝试兜底（记录提示）
        try:
            src = img.get_attribute("src") or "" if img else ""
        except Exception:
            src = ""
        if src.startswith("http") and not any(k in src for k in ("verify", "captcha", "code", "random")):
            raw = self.fetch_image_bytes(page, src)
            if raw:
                self.log("  ↻ 页面上的静态验证码图已改用接口直接取图")
                return raw, "接口取图"

        return None, ""

    def _fill_captcha_input(self, page, scope_selector: str, text: str) -> bool:
        """把识别结果填进验证码输入框。

        填入前记录当前图片的 src，填入后若发现图片 src 发生了变化（被网站自动冲掉了），
        则返回 False 提示重新对齐最新图片，避免提交作废验证码。
        """
        js = """
        (arg)=>{
          const root = arg.scope ? document.querySelector(arg.scope) : document;
          if(!root) return 'NO_SCOPE';
          const all=[...root.querySelectorAll('input:not([type=hidden]),textarea')];
          let inp=all.find(e=>/验证码|校验码|图形码|code|captcha/i.test(
                (e.getAttribute('placeholder')||'')+' '+
                (e.getAttribute('name')||'')+' '+(e.getAttribute('id')||'')));
          if(!inp){
            inp=all.find(e => !/搜索|查询主体|请输入主体名称/.test(e.placeholder||''));
          }
          if(!inp) return 'NO_INPUT';
          inp.focus();
          const proto = inp.tagName==='TEXTAREA'
              ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(inp, arg.text);
          inp.dispatchEvent(new Event('input',{bubbles:true}));
          inp.dispatchEvent(new Event('change',{bubbles:true}));
          return 'OK';
        }
        """
        try:
            r = page.evaluate(js, {"scope": scope_selector, "text": text})
        except Exception:
            return False
        return str(r).startswith("OK")

    def _click_confirm(self, page, scope_selector: str,
                       verify_texts=("验证", "确认", "确定", "提交")) -> bool:
        """点「验证」按钮。

        先按**精确选择器**找（信用中国是 .vcodepop a.confirm），
        找不到再按文字找 —— 但只挑最内层的可点元素，
        避免点到包住按钮的容器 div（div.buttongroup 的 innerText 也含「验证」，
        点它等于没点，表现为「自动识别填入后不能提交」）。
        """
        js = """
        (arg)=>{
          const root = arg.scope ? document.querySelector(arg.scope) : document;
          if(!root) return 'NO_SCOPE';
          const want=(arg.texts||[]).map(t=>t.replace(/\\s+/g,''));
          const all=[...root.querySelectorAll(
              'a,button,input[type=submit],input[type=button],span,em,i,div,label')];
          const norm=e=>(e.innerText||e.value||e.getAttribute('title')||'')
                        .replace(/\\s+/g,'').trim();
          const hits=all.filter(e=>{
            const t=norm(e);
            if(!t) return false;
            if(!want.some(w=>t===w)) return false;
            const b=e.getBoundingClientRect();
            return b.width>=6 && b.height>=6;
          });
          if(!hits.length) return 'NONE';
          // 只保留「最内层」：如果某个命中元素还包含另一个命中元素，就丢掉它
          const leaves=hits.filter(e=>!hits.some(o=>o!==e && e.contains(o)));
          const hit=leaves[0]||hits[0];
          hit.click();
          return 'CLICK:'+hit.tagName+'.'+(hit.className||'');
        }
        """
        try:
            r = page.evaluate(js, {"scope": scope_selector, "texts": list(verify_texts)})
        except Exception:
            return False
        return str(r).startswith("CLICK")

    def _captcha_error(self, page, scope_selector: str) -> str:
        """读验证码弹层里的错误提示（如「验证码错误」）。没有就返回空串。"""
        js = """
        (arg)=>{
          const root = arg.scope ? document.querySelector(arg.scope) : document;
          if(!root) return '';
          const errs=[...root.querySelectorAll(
            '.errortip,.error,.err,.tips,.msg,.toast,[class*="error"]')];
          for(const e of errs){
            const t=(e.innerText||'').replace(/\\s+/g,'').trim();
            if(!t) continue;
            if(getComputedStyle(e).display==='none') continue;
            if(/验证码|正确|错误|失效|过期/.test(t)) return t.slice(0,40);
          }
          return '';
        }
        """
        try:
            r = page.evaluate(js, {"scope": scope_selector})
        except Exception:
            return ""
        return str(r).strip() if isinstance(r, str) else ""

    def solve_image_captcha(self, page, img_selector: str = "img",
                           scope_selector: str = "",
                           verify_texts=("验证", "确认", "确定", "提交"),
                           tries: int = 3,
                           confirm_selectors=(),
                           success_check=None) -> bool:
        """自动识别并提交图形验证码。成功返回 True；不可用返回 False。

        完整闭环（每一轮）：
          1. 取图（页面已加载的 <img>，取不到就用接口直接取字节）；
          2. 去干扰线 + 放大 -> 送打码服务识别；
          3. 填进验证码输入框；
          4. 点「验证」按钮（精确选择器优先，只点最内层元素）；
          5. 判定结果：站点提示「验证码错误」就**只换验证码图**再试下一轮。

        刷新只换图（点站点的「看不清? 换一张」/ 改 img.src 加时间戳），
        **绝不刷新整个页面** —— 刷新整页会把已经填好的主体名称冲掉。

        success_check：可选回调 success_check() -> bool，
        用来判断「验证码已经通过」（例如 cookie 已置位）。返回 True 也算成功。

        任何一步失败都返回 False，调用方应回落人工输入。
        """
        solver = self.client()
        if not solver:
            return False
        scope = None
        try:
            scope = page.query_selector(scope_selector) if scope_selector else None
        except Exception:
            scope = None

        rounds = max(1, int(tries))
        for attempt in range(1, rounds + 1):
            # ---------- 1) 取图 ----------
            raw, how = self._capture_captcha(page, img_selector, scope)
            if not raw:
                self.log("  ⚠ 拿不到验证码图片（第 %d 轮），刷新换图重试" % attempt)
                if attempt < rounds:
                    if not (_click_refresh(scope or page, self.log, scope_selector, self.nap)
                            or _reload_image(scope or page, img_selector, self.nap)):
                        self.nap(1.5)
                    continue
                return False
            if image_looks_blank(raw):
                self.log("  ↻ 验证码图片是空白（第 %d 轮），刷新换图重试" % attempt)
                if attempt < rounds:
                    if not (_click_refresh(scope or page, self.log, scope_selector, self.nap)
                            or _reload_image(scope or page, img_selector, self.nap)):
                        self.nap(1.5)
                    continue
                self.log("  ⚠ 验证码始终未显示出内容，自动识别无法进行")
                return False

            # ---------- 2) 识别 ----------
            text = ""
            try:
                data = preprocess_captcha(raw)
                fn_text = getattr(solver, "solve_image_to_text", None)
                if fn_text is not None:
                    text = fn_text(data)
                elif hasattr(solver, "solve_captcha_image_element"):
                    text = solver.solve_captcha_image_element(None)
            except Exception as exc:
                self.log("  ⚠ 验证码识别出错：%s" % str(exc).splitlines()[0][:70])
                text = ""
            if not text:
                self.log("  ↻ 识别结果为空（第 %d 轮），刷新验证码重试" % attempt)
                if attempt < rounds:
                    if not (_click_refresh(scope or page, self.log, scope_selector, self.nap)
                            or _reload_image(scope or page, img_selector, self.nap)):
                        self.nap(1.5)
                    continue
                self.log("  ⚠ 打码服务没有返回有效结果")
                return False
            self.log("  ✔ 验证码自动识别完成（识别为 %s，来源：%s）" % (text, how or "图片"))

            # ---------- 3) 填入 ----------
            if not self._fill_captcha_input(page, scope_selector, text):
                self.log("  ⚠ 验证码输入框没找到")
                return False

            # ---------- 4) 提交 ----------
            # 填入后无需多余延迟，立即原子点击提交，抢在图片被网站自动更换前提交
            if confirm_selectors:
                hit = False
                for sel in confirm_selectors:
                    try:
                        r = page.evaluate(
                            "(sel)=>{const e=document.querySelector(sel);"
                            " if(!e) return 'NONE'; e.click(); return 'CLICK';}", sel)
                    except Exception:
                        r = "NONE"
                    if str(r).startswith("CLICK"):
                        hit = True
                        break
                if not hit:
                    hit = self._click_confirm(page, scope_selector, verify_texts)
            else:
                hit = self._click_confirm(page, scope_selector, verify_texts)
            if not hit:
                self.log("  ⚠ 验证码「验证」按钮没找到")
                return False
            self.log("  → 验证码已自动提交")

            # ---------- 5) 判定 ----------
            self.nap(1.5)
            if success_check is not None:
                try:
                    ok = bool(success_check())
                except Exception:
                    ok = False
                if ok:
                    return True
                err = self._captcha_error(page, scope_selector)
                if err:
                    self.log("  ✘ 站点提示「%s」，刷新验证码后重试" % err)
                else:
                    self.log("  ↻ 未通过，刷新验证码后重试")
            else:
                # 没传 success_check 时：只要没有显式报「验证码错误」，即视为提交成功
                err = self._captcha_error(page, scope_selector)
                if not err:
                    return True
                self.log("  ✘ 站点提示「%s」，刷新验证码后重试" % err)
            if attempt < rounds:
                # 只换验证码图，不刷新整个页面
                if not (_click_refresh(scope or page, self.log, scope_selector, self.nap)
                        or _reload_image(scope or page, img_selector, self.nap)):
                    self.nap(1.5)
                self.nap(1.0)
        return False


    def solve_frame_captcha(self, frame) -> bool:
        """在指定的 iframe（登录框）里自动识别并提交图形验证码。

        和 _solve_image_vcode 的区别：那个跑在主页面，这个跑在
        account.court.gov.cn 这种跨域 iframe 里。
        任何一步失败都返回 False，调用方回落人工输入。
        """
        solver = self.client()
        if not solver or frame is None:
            return False
        try:
            # 0) 天艾滑块/点选：官方打码题型不支持，只能人工
            #    实测真机类名：.tianai-captcha-dialog / .tianai-captcha-mask /
            #    .tianai-captcha-popup / .tianai-captcha-slider
            try:
                has_tianai = bool(frame.evaluate("""
                ()=>!!(document.querySelector('[id^=tianai-captcha]')
                        || document.querySelector('[class^=tianai-captcha]')
                        || document.querySelector('[class*="tianai-captcha-dialog"]')
                        || document.querySelector('.tianai-captcha-ui-overlay'))"""))
            except Exception:
                has_tianai = False
            if has_tianai:
                self.log("  ⓘ 登录框是滑块/点选验证码（打码服务不支持），请人工完成")
                return False

            # 1) 找验证码图片：先按常见特征找，找不到再按「尺寸像验证码」兜底
            img = None
            img_sel = ""
            for sel in ("img[src*='code' i]", "img[src*='captcha' i]",
                        "img[src*='verify' i]", ".captcha img", ".code-img",
                        "#captchaImg", "#vcodeimg", "img[class*='code' i]",
                        "img[id*='code' i]"):
                try:
                    img = frame.query_selector(sel)
                except Exception:
                    img = None
                if img:
                    img_sel = sel
                    break
            if img is None:
                try:
                    imgs = frame.query_selector_all("img")
                except Exception:
                    imgs = []
                for it in imgs:
                    try:
                        box = it.bounding_box()
                    except Exception:
                        continue
                    if not box:
                        continue
                    w, h = box.get("width", 0), box.get("height", 0)
                    if 45 <= w <= 260 and 18 <= h <= 120:
                        img = it
                        break
            if img is None:
                self.log("  ⚠ 登录框里没找到验证码图片，无法自动识别")
                return False

            # 1.5) 必须有明确的「验证码输入框」才能自动填，否则宁可交给人工
            has_code_input = bool(frame.evaluate("""
            ()=>[...document.querySelectorAll('input:not([type=hidden]),textarea')]
                 .some(e=>/验证码|校验码|图形码|code|captcha/i.test(
                     (e.getAttribute('placeholder')||'') + ' ' +
                     (e.getAttribute('name')||'') + ' ' + (e.getAttribute('id')||'')))"""))
            if not has_code_input:
                self.log("  ⚠ 登录框没有验证码输入框（不是图形码），请人工完成")
                return False

            # 2) 送去打码服务（带刷新重试：图片第一次可能是白板）
            text = ""
            for attempt in range(1, 4):
                try:
                    raw = img.screenshot(timeout=20000)
                    if image_looks_blank(raw):
                        self.log("  ↻ 登录验证码图片是空白（第 %d 次），刷新重试" % attempt)
                        if attempt < 3:
                            if not _click_refresh(frame, self.log):
                                if img_sel:
                                    _reload_image(frame, img_sel)
                                else:
                                    self.nap(1.2)
                            continue
                        self.log("  ⚠ 登录验证码始终未显示出内容")
                        return False
                    text = solver.solve_image_to_text(preprocess_captcha(raw))
                except Exception as exc:
                    self.log("  ⚠ 登录验证码截图/识别出错：%s"
                             % str(exc).splitlines()[0][:70])
                    text = ""
                if text:
                    break
                if attempt < 3:
                    self.log("  ↻ 登录验证码识别为空（第 %d 次），刷新重试" % attempt)
                    if not _click_refresh(frame, self.log):
                        self.nap(1.2)
            if not text:
                self.log("  ⚠ 打码服务没有返回结果")
                return False
            self.log("  ✔ 登录验证码自动识别完成（识别为 %s）" % text)

            # 3) 填进验证码输入框（优先带「验证码/code」特征的框）
            js_fill = """
            (t)=>{
              const feat = e => /验证码|校验码|图形码|code|captcha/i.test(
                    (e.getAttribute('placeholder')||'') + ' ' +
                    (e.getAttribute('name')||'') + ' ' + (e.getAttribute('id')||''));
              const all = [...document.querySelectorAll(
                    'input:not([type=hidden]),textarea')];
              let inp = all.find(feat);
              if(!inp){
                inp = all.find(e => {
                  if ((e.getAttribute('type')||'').toLowerCase()==='password') return false;
                  const b = e.getBoundingClientRect();
                  return b.width > 20 && b.height > 10;
                });
              }
              if(!inp) return 'NO_INPUT';
              inp.focus();
              const proto = inp.tagName==='TEXTAREA'
                  ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              Object.getOwnPropertyDescriptor(proto,'value').set.call(inp, t);
              inp.dispatchEvent(new Event('input',{bubbles:true}));
              inp.dispatchEvent(new Event('change',{bubbles:true}));
              return 'OK';
            }
            """
            r = frame.evaluate(js_fill, text)
            if not str(r).startswith("OK"):
                self.log("  ⚠ 验证码输入框没找到（%s）" % r)
                return False

            # 4) 点提交（只挑最内层的元素，避免点到包住按钮的容器 div）
            js_click = """
            ()=>{
              const norm = s => (s||'').replace(/\\s+/g,'');
              const want = ['登录','验证','确定','提交','确认'];
              const all=[...document.querySelectorAll(
                  'button,a,span,div,i,label,input[type=submit]')].filter(el=>{
                const t = norm(el.innerText || el.value || '');
                if(!t) return false;
                if(!want.some(w=>t===w || t.indexOf(w)>=0)) return false;
                const b = el.getBoundingClientRect();
                return b.width>=6 && b.height>=6;
              });
              if(!all.length) return '';
              const leaves=all.filter(el=>!all.some(o=>o!==el && el.contains(o)));
              const hit=leaves[0]||all[0];
              hit.click();
              return norm(hit.innerText || hit.value || '');
            }
            """
            hit = frame.evaluate(js_click)
            if not hit:
                self.log("  ⚠ 验证码提交按钮没找到")
                return False
            self.log("  → 登录验证码已自动提交")
            return True
        except Exception as exc:
            self.log("  ⚠ 登录验证码自动识别失败：%s" % exc)
            return False


    def solve_recaptcha(self, page) -> bool:
        """自动识别并提交页面上的 reCAPTCHA v2。成功返回 True。"""
        solver = self.client()
        if not solver:
            return False
        try:
            site_key = page.evaluate("""
            ()=>{const el=document.querySelector('.g-recaptcha[data-sitekey]');
                  return el?el.getAttribute('data-sitekey'):'';}""")
            if not site_key:
                return False
            url = page.url
            self.log("  → 提交 reCAPTCHA v2 到打码服务…")
            token = solver.solve_recaptcha_v2(site_key, url)
            r = page.evaluate("""
            (tok)=>{
              const ta=document.querySelector('textarea[name="g-recaptcha-response"]');
              if(!ta) return 'NO_TA';
              ta.value=tok;
              ta.dispatchEvent(new Event('change',{bubbles:true}));
              return 'OK';
            }""", token)
            if r != "OK":
                self.log("  ⚠ reCAPTCHA token 注入失败")
                return False
            self.log("  ✔ reCAPTCHA 已自动识别并注入")
            return True
        except Exception as exc:
            self.log("  ⚠ reCAPTCHA 自动识别失败：%s" % exc)
            return False
