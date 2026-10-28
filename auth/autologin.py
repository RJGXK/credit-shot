# -*- coding: utf-8 -*-
"""自动登录：按平台的登录流程，把账号密码填进去并提交。

设计要点
--------
1. **按平台分派**：每个平台一条流程函数，放在 FLOWS 里；
   没实现的平台返回「暂不支持自动登录」，引擎会回落人工处理。
2. **验证码交给人工，但只让人工做最小的那一步**：
   账号密码由程序自动填好；遇到图形验证码 / 滑块 / 点选 / 短信验证时，
   程序**挂起**并在浏览器里把光标带到验证码处，人工只补验证码，
   然后点【我已处理，继续截图】，程序继续点「登录」并判定结果。
   —— 这样人工不必从头登录，只是补一个验证码。
3. **只读不误伤**：全程只用 Playwright 操作页面，不碰系统设置。

裁判文书网的特殊性
------------------
登录不是本页表单，而是弹一个 **跨域 iframe**
（https://account.court.gov.cn/oauth/authorize?...），
所以要在 frame 里操作。Playwright 不受同源策略限制，可以直接操作。
表单是 Vue 写的，填值必须走**原生 setter + input/change 事件**，
否则 v-model 收不到值，提交时会是空。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.page import js_action as _page_js_action
from core.page import read_text as _page_read_text

__all__ = ["LoginResult", "try_login", "FLOWS"]

LogFn = Callable[[str], None]
# 引擎提供的「等待人工处理验证码」回调：返回后引擎会继续往下走
WaitCaptchaFn = Callable[[str], None]
# 引擎提供的「打码服务自动过验证码」回调：传入登录框 frame，
# 返回 True 表示已经识别并提交成功，False 表示失败（回落人工）
SolveCaptchaFn = Callable[[object], bool]


@dataclass
class LoginResult:
    """一次自动登录的结果。"""

    ok: bool = False
    reason: str = ""            # 失败原因 / 成功说明
    filled: bool = False        # 账号密码是否已填好
    needs_captcha: bool = False # 是否卡在验证码/滑块等人工环节
    bad_credentials: bool = False  # 是否明确提示账号或密码错误

    @property
    def summary(self) -> str:
        if self.ok:
            return "自动登录成功"
        if self.bad_credentials:
            return "账号或密码不正确"
        if self.needs_captcha:
            return "需要人工完成验证码"
        return self.reason or "自动登录未完成"


# ------------------------------------------------------------------ 填值助手
# 说明：Vue 受控组件必须走「原生 setter + input/change 事件」，
# 直接 el.value = x 是不会更新 v-model 的。
_SET_VALUE_JS = """
([sel, value]) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.blur();
  return true;
}
"""


def _js_action(target, js: str, arg=None, timeout: int = 5000):
    """执行一段页面 JS，成功返回 True。

    具体实现放在 core.page.js_action（通用能力），这里只是转发，
    保持 autologin 里的调用写法不变。

    注意：evaluate 回落路径**原样返回**脚本结果（可能是字符串），
    这样调用方才能判断「OK/OK」这类具体状态。
    """
    return _page_js_action(target, js, arg, timeout)


def _read_text(target) -> str:
    """读页面/iframe 的正文文本（带超时保护）。

    实现在 core.page.read_text（通用能力）。
    """
    return _page_read_text(target)


def _fill(frame, keyword: str, value: str, kind: str = "text") -> bool:
    """在 frame 里按 placeholder 关键字填一个输入框。

    一次 evaluate 完成「找到 + 赋值 + 派发事件」，
    不再用 `#id` 二次查询 —— 真机上很多输入框只有 name 没有 id，
    用 #name 查是查不到的（真机验证过的坑）。
    """
    if not value:
        return False
    js = """
    ([kw, kind, value]) => {
      const els = Array.from(document.querySelectorAll('input,textarea'));
      const hit = els.find(e => {
        const ph = (e.getAttribute('placeholder') || '');
        const ty = (e.getAttribute('type') || '').toLowerCase();
        if (kind === 'password') {
          return ty === 'password' || /密码|密碼|password|passwd/i.test(ph);
        }
        if (kw && ph.indexOf(kw) >= 0) return true;
        if (ty === 'password') return false;
        return /账号|帳號|用户名|user|account|手机号|手机號|mobile|phone|手机/i.test(ph);
      });
      if (!hit) return false;
      const proto = hit instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(hit, value);
      hit.dispatchEvent(new Event('input', {bubbles: true}));
      hit.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    """
    return bool(_js_action(frame, js, [keyword, kind, value]))


def _click_text(frame, texts, exact: bool = False) -> bool:
    """在 frame 里点击文字匹配的按钮/链接。"""
    js = """
    ([texts, exact]) => {
      const norm = s => (s || '').replace(/\\s+/g, '');
      const want = texts.map(norm);
      const els = Array.from(document.querySelectorAll(
          'button,a,span,div,i,label,input[type=submit]'));
      for (const el of els) {
        const t = norm(el.innerText || el.value || '');
        if (!t) continue;
        const ok = exact ? want.indexOf(t) >= 0
                         : want.some(w => t === w || t.indexOf(w) >= 0);
        if (!ok) continue;
        if (el.children.length > 2) continue;
        const b = el.getBoundingClientRect();
        if (b.width < 6 || b.height < 6) continue;
        el.click();
        return true;
      }
      return false;
    }
    """
    try:
        if _js_action(frame, js, [list(texts), bool(exact)]):
            return True
    except Exception:
        return False


def _frame_text(frame) -> str:
    try:
        return _read_text(frame)
    except Exception:
        return ""


def _page_text(page) -> str:
    try:
        return _read_text(page)
    except Exception:
        return ""


# ------------------------------------------------------------------ 裁判文书网
def _find_wenshu_login_frame(page, timeout: float = 35.0):
    """等登录 iframe（account.court.gov.cn）挂载。

    页面里同时存在两个同域 iframe：
      · /oauth/authorize?...   —— 授权回调用，通常是空壳
      · /app?back_url=...#/login —— 真正的登录表单
    所以优先挑「里面有密码框」的那个，其次挑 /app 那个。

    注意：Playwright 的 ``query_selector`` **不接受 timeout 参数**
    （只有 ``wait_for_selector`` 才有），传了会直接抛 TypeError。
    这里统一用短超时的 ``wait_for_selector``。
    """
    deadline = time.time() + timeout
    fallback = None
    while time.time() < deadline:
        cands = []
        try:
            for f in page.frames:
                if "account.court.gov.cn" in (f.url or ""):
                    cands.append(f)
        except Exception:
            pass
        # 1) 有密码框的才是登录表单
        for f in cands:
            try:
                # 必须给短超时：跨域 iframe 可能迟迟不加载，默认 30 秒
                # 会把登录流程拖成好几分钟
                if f.wait_for_selector("input[type=password]", timeout=1200):
                    return f
            except Exception:
                continue
        # 2) 其次挑带 back_url 的那个（扫码那个是 app#/scan，没有密码框）
        for f in cands:
            u = f.url or ""
            if "/app?" in u:
                fallback = f
                break
        if fallback is None:
            for f in cands:
                if "#/login" in (f.url or ""):
                    fallback = f
                    break
        if fallback is not None:
            return fallback
        # 3) 最后退回第一个同域 iframe
        if cands:
            fallback = cands[0]
        time.sleep(0.6)
    return fallback


def _open_wenshu_login(page, timeout: float = 20.0) -> bool:
    """点开右上角的「登录」入口。

    站点是 SPA，导航栏可能晚好几秒才渲染出来，所以要重试；
    JS click 失败再退回 Playwright 的真实点击（<li id="loginLi">）。
    """
    js = """
    ()=>{
      for (const x of document.querySelectorAll('a,span,div,li,button')) {
        const t = (x.innerText||'').trim();
        if (!t || t.length > 6 || x.children.length > 0) continue;
        if (!/^登录$|^登\\s*录$|^登录\\/?注册$/.test(t)) continue;
        const b = x.getBoundingClientRect();
        if (b.width < 4 || b.height < 4) continue;
        x.click();
        return true;
      }
      return false;
    }
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 用带超时的 _js_action：页面 JS 线程忙时不会无限期卡住
        if _js_action(page, js, timeout=2500):
            return True
        for sel in ("#loginLi", "a[href*='login']"):
            try:
                el = page.wait_for_selector(sel, timeout=2000)
                if el:
                    el.click(timeout=2500)
                    return True
            except Exception:
                continue
        time.sleep(1.5)
    return False


def _submit_wenshu(frame, log: LogFn) -> bool:
    """点「提交登录」。

    真机结构：提交按钮是 <div class="login-button-container">登录</div>，
    页面里同时还有「忘记密码」链接和国家区号下拉（里面也有可见文字），
    所以优先用类名定位，兜底才按文字**精确**匹配。
    """
    for sel in (".login-button-container", "div[class*='login-button']"):
        try:
            el = frame.wait_for_selector(sel, timeout=2000)
            if el:
                el.click(timeout=5000)
                return True
        except Exception:
            continue
    return _click_text(frame, ["登录"], exact=True) or \
        _click_text(frame, ["确定"], exact=True)


def _ws_frame_alive(page) -> bool:
    try:
        return any("account.court.gov.cn" in (f.url or "") for f in page.frames)
    except Exception:
        return False


def _ws_judge(page, frame, log: LogFn):
    """判定登录结果。返回 (状态, 说明)；状态 ∈ ok / captcha / badcred / unknown。"""
    alive = _ws_frame_alive(page)
    txt = _frame_text(frame) if (alive and frame is not None) else ""
    ptext = _page_text(page)

    if not alive:
        return "ok", "登录窗口已关闭"
    # 成功标志只看「主页面」文本，避免登录框里的「用户名」等字样误判
    if re.search(r"退出|注销|个人中心|欢迎您|已登录|登录成功", ptext):
        return "ok", "页面已显示登录用户信息"
    # 登录框自身提示成功
    if re.search(r"登录成功|已登录", txt):
        return "ok", "登录框提示登录成功"
    # 账号密码错误优先于验证码判定：
    # 页面常同时显示「密码错误」和验证码元素，先判验证码会掩盖真实原因。
    if re.search(r"密码错误|密码不正确|账号不存在|帐号不存在|账号或密码|用户名或密码|登录失败", txt):
        return "badcred", "账号或密码不正确"
    if re.search(r"验证码|安全验证|拖动|滑块|点选|按顺序|依次点击|天艾|请点击|短信验证|人机|请完成验证",
                 txt + ptext):
        return "captcha", "需要人工完成验证码"
    return "unknown", "登录后未确认结果"


def _login_wenshu(page, username: str, password: str, log: LogFn,
                  wait_captcha: Optional[WaitCaptchaFn] = None,
                  solve_captcha: Optional[SolveCaptchaFn] = None) -> LoginResult:
    """裁判文书网自动登录（手机号 + 密码），验证码可交人工输入。"""
    # 1) 打开登录入口（站点偶发打不开 / 加载慢，重试并刷新）
    frame = None
    # 找登录窗的总预算：没有它的话，登录窗迟迟不出时会一直重试下去，
    # 用户只看到程序卡住却不知道卡在哪一步。
    budget = time.time() + 75
    for attempt in range(3):
        remain = budget - time.time()
        if remain < 5:
            break
        # ① 先看登录窗是不是已经在页面里了。
        #    点【检索】之后，未登录时站点通常会**自己弹出**统一身份认证窗口；
        #    这时候页面正在跳转，再去点导航栏的「登录」容易把流程卡死。
        frame = _find_wenshu_login_frame(page, min(6.0, remain))
        if frame is not None:
            log("  ✔ 已找到统一身份认证登录窗口")
            break
        # ② 没有再点导航栏的「登录」入口
        log("  … 打开统一身份认证登录窗口（第 %d 次尝试）" % (attempt + 1))
        _open_wenshu_login(page, timeout=8.0)
        remain = budget - time.time()
        if remain < 5:
            break
        frame = _find_wenshu_login_frame(page, min(20.0, remain))
        if frame is not None:
            log("  ✔ 已找到统一身份认证登录窗口")
            break
        log("  … 登录窗口还没出来（第 %d 次未成功）" % (attempt + 1))
        if attempt < 2:
            try:
                page.reload(timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
            except Exception:
                pass
    if frame is None:
        log("  ⚠ 登录窗口（统一身份认证）没有加载出来 —— "
            "请手动在浏览器窗口里登录，或稍后重试")
        return LoginResult(reason="登录窗口未加载")

    try:
        frame.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    time.sleep(1.2)

    # 3) 填手机号 + 密码
    #    真机结构：<input name="username" placeholder="手机号码"> +
    #              <input type="password" placeholder="密码">
    ok_user = _fill(frame, "手机", username, kind="account") or \
        _fill(frame, "", username, kind="account")
    ok_pass = _fill(frame, "", password, kind="password")
    if not (ok_user and ok_pass):
        log("  ⚠ 账号或密码框没找到（账号=%s 密码=%s）"
            % ("OK" if ok_user else "失败", "OK" if ok_pass else "失败"))
        return LoginResult(reason="登录表单没找到账号/密码输入框")
    log("  ✔ 账号密码已自动填入登录窗口")

    # 4) 点提交
    if _submit_wenshu(frame, log):
        log("  → 已提交登录…")
    else:
        log("  ⚠ 没找到提交按钮")

    # 6) 判定；遇到验证码就交给人工（账号密码已填好，人工只补验证码）
    #    判定窗口给到 40 秒：账号密码错误/天艾点选弹窗都可能延后出现，
    #    窗口太短会直接判成「未确认结果」，用户看不到任何提示。
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(1.2)
        state, msg = _ws_judge(page, frame, log)
        if state == "ok":
            log("  ✔ 自动登录成功（%s）" % msg)
            return LoginResult(ok=True, reason=msg, filled=True)
        if state == "badcred":
            log("  ⚠ 提示账号或密码不正确")
            return LoginResult(reason=msg, filled=True, bad_credentials=True)
        if state == "captcha":
            # —— 第一步：打码服务自动过（配了 API Key 才会走到这里）——
            if solve_captcha is not None:
                try:
                    done = bool(solve_captcha(frame))
                except Exception as exc:
                    done = False
                    log("  ⚠ 打码服务处理验证码时出错：%s" % exc)
                if done:
                    log("  ✔ 验证码已由打码服务自动完成")
                    deadline3 = time.time() + 20
                    while time.time() < deadline3:
                        time.sleep(1.2)
                        state3, msg3 = _ws_judge(page, frame, log)
                        if state3 == "ok":
                            log("  ✔ 自动登录成功（%s）" % msg3)
                            return LoginResult(ok=True, reason=msg3, filled=True)
                        if state3 == "badcred":
                            return LoginResult(reason=msg3, filled=True,
                                               bad_credentials=True)
                        if state3 == "captcha":
                            break
                    log("  → 打码后验证码仍未通过，转人工处理")
            if wait_captcha is None:
                log("  ⚠ 登录需要人工完成验证码")
                return LoginResult(reason=msg, filled=True, needs_captcha=True)
            # —— 交给人工：账号密码已填好，人工只补验证码/滑块 ——
            log("  ⏸ 账号密码已填好，请在浏览器里完成验证码")
            wait_captcha(
                "裁判文书网登录需要人工完成验证码：账号密码已由程序自动填好，"
                "请在浏览器窗口里按提示完成验证（天艾点选 / 滑块 / 图形码 / 短信码），"
                "完成后点【我已处理，继续截图】。")
            # 人工可能已经自己点了提交；若登录框还在，程序再点一次
            if _ws_frame_alive(page):
                time.sleep(0.8)
                _submit_wenshu(frame, log)
                log("  → 已再次提交登录…")
            # 再判定一轮
            deadline2 = time.time() + 25
            while time.time() < deadline2:
                time.sleep(1.2)
                state2, msg2 = _ws_judge(page, frame, log)
                if state2 == "ok":
                    log("  ✔ 人工补完验证码后登录成功（%s）" % msg2)
                    return LoginResult(ok=True, reason=msg2, filled=True)
                if state2 == "badcred":
                    return LoginResult(reason=msg2, filled=True, bad_credentials=True)
                if state2 == "captcha":
                    return LoginResult(reason="验证码仍未通过", filled=True,
                                       needs_captcha=True)
            return LoginResult(reason="验证码后仍未确认登录结果", filled=True,
                               needs_captcha=True)

    log("  ⚠ 登录后没有等到明确结果")
    return LoginResult(reason="登录后未确认结果", filled=True)


# ------------------------------------------------------------------ 国家企业信用信息公示系统
def _gsxt_has_geetest(page) -> bool:
    """页面上有没有极验验证（geetest）面板。"""
    try:
        return bool(page.evaluate("""()=>{
          const els=[...document.querySelectorAll('[class*=geetest],[id*=geetest]')];
          return els.some(e=>{
            const b=e.getBoundingClientRect();
            return b.width>100 && b.height>60;});}"""))
    except Exception:
        return False


def _gsxt_open_login(page, log: LogFn, timeout: float = 25.0) -> bool:
    """点开 gsxt 的登录页。

    实测（2026-10）：gsxt 首页的「登录」是**整页跳转**到实名认证子站
    ``shiming.gsxt.gov.cn/socialuser-use-rllogin.html``，
    登录表单（#UserName / #gsxtp / #btn_login）在那个页面上。
    所以这里点击后要等**页面跳转**完成，而不是等同页弹窗出现。
    """
    js = """
    ()=>{
      // 已在登录页就直接算成功
      if(document.getElementById('UserName')) return 'ALREADY';
      const norm=s=>(s||'').replace(/\\s+/g,'').trim();
      const els=[...document.querySelectorAll('a,span,div,li,button')];
      // 优先找导航栏里独立的「登录」（不要点到「用户登录」「登录注册」这类长文字）
      const hit=els.find(e=>{
        const t=norm(e.innerText||e.textContent||'');
        if(t!=='登录') return false;
        const b=e.getBoundingClientRect();
        return b.width>0 && b.height>0;});
      if(!hit) return 'NONE';
      hit.click(); return 'CLICK';
    }
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 用 eval_retry 拿**脚本真实返回值**（"ALREADY"/"CLICK"/"NONE"）。
        # 不能用 _js_action：它走 wait_for_function 时只回 True/False，
        # 字符串结果会被丢掉（selftest 也踩过这个坑）。
        try:
            from core.page import eval_retry
            r = str(eval_retry(page, js, None, tries=1, delay=0.5) or "")
        except Exception:
            # 整页跳转进行中，上下文销毁属正常
            r = ""
        if r == "ALREADY":
            return True
        if r.startswith("CLICK"):
            # 等跳转完成 + 登录表单出现（最多 15 秒）
            d2 = time.time() + 15
            while time.time() < d2:
                time.sleep(1.5)
                try:
                    if page.evaluate(
                            "()=>!!document.getElementById('UserName')"):
                        log("  ✔ 已进入 gsxt 登录页（shiming.gsxt.gov.cn）")
                        return True
                except Exception:
                    pass
        time.sleep(1.5)
    # 兜底：直接打开登录子站页
    try:
        page.goto("https://shiming.gsxt.gov.cn/socialuser-use-rllogin.html",
                  wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        if page.evaluate("()=>!!document.getElementById('UserName')"):
            log("  ✔ 已直达 gsxt 登录页")
            return True
    except Exception:
        pass
    return False
    return False


def _gsxt_fill(page, username: str, password: str) -> str:
    """填 gsxt 登录框：#UserName（手机号/身份证号）+ #gsxtp（密码）。

    这里用 eval_retry 而不是 _js_action：需要拿到脚本返回的**具体字符串**
    （"OK/OK" 表示两个框都填成功），而 wait_for_function 只会返回 True。
    """
    js = """
    (arg)=>{
      const set=(id,v)=>{
        const e=document.getElementById(id);
        if(!e) return 'NO_'+id;
        e.focus();
        const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(e,v);
        e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true}));
        return e.value===v ? 'OK' : 'SET_FAIL';
      };
      return [set('UserName',arg.u), set('gsxtp',arg.p)].join('/');
    }
    """
    try:
        from core.page import eval_retry
        r = eval_retry(page, js, {"u": username, "p": password}, tries=3, delay=0.8)
    except Exception:
        return ""
    return r if isinstance(r, str) else ""


def _gsxt_submit(page) -> bool:
    """点 gsxt 登录按钮 #btn_login。"""
    js = """
    ()=>{
      const b=document.getElementById('btn_login');
      if(!b) return false;
      b.focus();
      b.click();
      return true;
    }
    """
    ok = bool(_js_action(page, js, timeout=4000))
    if not ok:
        try:
            b = page.query_selector("#btn_login")
            if b:
                b.click()
                return True
        except Exception:
            pass
    return ok


def _gsxt_judge(page, log: LogFn):
    """判定 gsxt 登录结果，返回 (状态, 说明)；状态 ∈ ok / captcha / badcred / unknown。"""
    text = _page_text(page)
    if not text:
        return "unknown", "登录后未读到页面内容"
    if re.search(r"退出|注销|个人中心|欢迎您|已登录|退出登录", text):
        return "ok", "页面已显示登录用户信息"
    if _gsxt_has_geetest(page):
        return "captcha", "需要人工完成滑块/点选验证"
    if re.search(r"密码错误|账号不存在|帐号不存在|用户名或密码|不正确|登录失败|手机号未注册",
                 text):
        return "badcred", "账号或密码不正确"
    if re.search(r"请输入密码|请输入手机号", text):
        return "unknown", "登录框仍在（未提交成功）"
    return "unknown", "登录后未确认结果"


def _login_gsxt(page, username: str, password: str, log: LogFn,
                wait_captcha: Optional[WaitCaptchaFn] = None,
                solve_captcha: Optional[WaitCaptchaFn] = None) -> LoginResult:
    """国家企业信用信息公示系统自动登录。

    实测结构（与裁判文书网完全不同）：
      · 登录框在**主页面**里，不是 iframe：``.loginBox``
        - ``#UserName``  手机号 / 身份证号
        - ``#gsxtp``      密码
        - ``#btn_login``  登录按钮
      · 提交后如果账号密码正确会弹出**极验 geetest 点选/滑块**
        （``选 3 个符合右图的图片``），官方打码题型不支持，只能人工；
      · 若站点另有图形验证码（``#popup-captcha``），打码服务可以自动过。
    """
    if not _gsxt_open_login(page, log):
        log("  ⚠ gsxt 登录框没有打开 —— 请手动在浏览器窗口里登录，或稍后重试")
        return LoginResult(reason="登录框未打开")

    res = _gsxt_fill(page, username, password)
    if not res.startswith("OK"):
        log("  ⚠ 账号或密码框没找到（%s）" % res)
        return LoginResult(reason="登录表单没找到账号/密码输入框")
    log("  ✔ 账号密码已自动填入 gsxt 登录框")

    if not _gsxt_submit(page):
        log("  ⚠ 没找到登录按钮")
        return LoginResult(reason="没找到登录按钮", filled=True)
    log("  → 已提交登录…")

    deadline = time.time() + 25
    while time.time() < deadline:
        time.sleep(1.5)
        state, msg = _gsxt_judge(page, log)
        if state == "ok":
            log("  ✔ 自动登录成功（%s）" % msg)
            return LoginResult(ok=True, reason=msg, filled=True)
        if state == "badcred":
            log("  ⚠ 提示账号或密码不正确")
            return LoginResult(reason=msg, filled=True, bad_credentials=True)
        if state == "captcha":
            # 先试打码服务（站点若同时有图形验证码）
            if solve_captcha is not None:
                try:
                    done = bool(solve_captcha(page))
                except Exception as exc:
                    done = False
                    log("  ⚠ 打码服务处理验证码时出错：%s" % exc)
                if done:
                    log("  ✔ 验证码已由打码服务自动完成")
                    d3 = time.time() + 20
                    while time.time() < d3:
                        time.sleep(1.2)
                        s3, m3 = _gsxt_judge(page, log)
                        if s3 == "ok":
                            return LoginResult(ok=True, reason=m3, filled=True)
                        if s3 == "badcred":
                            return LoginResult(reason=m3, filled=True,
                                               bad_credentials=True)
                        if s3 == "captcha":
                            break
            if wait_captcha is None:
                log("  ⚠ gsxt 登录需要人工完成验证")
                return LoginResult(reason=msg, filled=True, needs_captcha=True)
            log("  ⏸ 账号密码已填好，请在浏览器里完成验证")
            wait_captcha(
                "国家企业信用信息公示系统登录需要人工完成验证：账号密码已由程序自动填好，"
                "请在浏览器窗口里完成滑块 / 点选 / 图形码验证，"
                "完成后点【我已处理，继续截图】。")
            if not _gsxt_has_geetest(page):
                _gsxt_submit(page)
                log("  → 已再次提交登录…")
            d2 = time.time() + 60
            jumped_home = False
            while time.time() < d2:
                time.sleep(1.5)
                # 瑞数 WAF 遇到白页或环境检测页，等待其放行
                try:
                    title = page.title() or ""
                    if "Environment Checking" in title or "环境检测" in title or "请稍候" in title:
                        continue
                except Exception:
                    pass

                # ★ 先查「是否已跳回首页」再查极验：
                # gsxt 登录成功后**整页跳回** www.gsxt.gov.cn/index.html（实测），
                # 登录页句柄上什么成功标志都没有；极验弹层 DOM 还可能残留，
                # 先走 _gsxt_judge 会一直误判 captcha 死循环。
                try:
                    cur_url = page.url or ""
                    if "shiming.gsxt.gov.cn" not in cur_url:
                        # 已离开登录子站：回到首页 = 登录成功
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                        time.sleep(2.0)
                        log("  ✔ 登录成功：已从登录页跳回首页")
                        return LoginResult(ok=True, reason="登录后跳回首页",
                                           filled=True)
                except Exception:
                    pass

                s2, m2 = _gsxt_judge(page, log)
                if s2 == "ok":
                    log("  ✔ 人工补完验证后登录成功（%s）" % m2)
                    return LoginResult(ok=True, reason=m2, filled=True)
                if s2 == "badcred":
                    return LoginResult(reason=m2, filled=True, bad_credentials=True)
                if s2 == "captcha":
                    # 滑块可能还在，等待一会儿
                    time.sleep(1.0)
                    continue

                # 兜底：页面上下文里能读到首页搜索框也算登录成功
                try:
                    has_kw = page.evaluate("()=>!!document.getElementById('keyword')")
                    if has_kw:
                        log("  ✔ 登录重定向完成，首页已就绪")
                        return LoginResult(ok=True, reason="登录重定向完成", filled=True)
                except Exception:
                    pass

    log("  ⚠ 登录后没有等到明确结果")
    return LoginResult(reason="登录后未确认结果", filled=True)


# ------------------------------------------------------------------ 分派
FLOWS = {
    "wenshu": _login_wenshu,
    "gsxt": _login_gsxt,
}


def try_login(page, platform_key: str, username: str, password: str,
              log: LogFn = print,
              wait_captcha: Optional[WaitCaptchaFn] = None,
              solve_captcha: Optional[SolveCaptchaFn] = None) -> LoginResult:
    """按平台执行自动登录。返回结果对象（不抛异常）。

    wait_captcha：可选回调，引擎用它挂起等待人工输入验证码；
    回调返回后流程会继续点「登录」并再次判定。
    solve_captcha：可选回调，引擎用它调打码服务自动过验证码；
    返回 False 时自动回落人工。
    """
    if not username or not password:
        return LoginResult(reason="未配置账号或密码")
    fn = FLOWS.get(platform_key)
    if fn is None:
        return LoginResult(reason="该平台暂不支持自动登录，请手动登录")
    try:
        return fn(page, username, password, log, wait_captcha, solve_captcha)
    except Exception as exc:
        return LoginResult(reason="自动登录异常：%s" % exc)
