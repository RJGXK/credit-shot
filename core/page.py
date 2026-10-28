# -*- coding: utf-8 -*-
"""core/page.py —— 页面动作原语。

「填一个框 / 点一个按钮 / 等一个元素」是所有站点都要用的动作，
集中放在这里，各个平台模块直接调用，避免每个平台各写一遍。

注意：这些是普通函数（不是方法），入参是 Playwright 的 page/frame 对象，
这样它们不依赖 Engine 状态，可以单独测试。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

__all__ = [
    "fill_controlled", "set_native", "click_by_text", "wait_text",
    "wait_ready", "eval_retry", "read_text", "js_action",
]


def js_action(target, js: str, arg=None, timeout: int = 5000):
    """执行一段页面 JS（带超时保护）。

    为什么不用 evaluate：Playwright 的 evaluate **没有超时参数**，
    页面正在导航（JS 线程忙）时它会一直等，整个流程就卡在这一步。
    wait_for_function 有超时且会轮询重试。

    没有 wait_for_function 的环境（老版本 / 测试替身）回落到 evaluate，
    此时**原样返回**脚本结果（可能是字符串），调用方自行判断。
    """
    fn = getattr(target, "wait_for_function", None)
    if fn is not None:
        try:
            if arg is None:
                fn(js, timeout=timeout)
            else:
                fn(js, arg=arg, timeout=timeout)
            return True
        except AttributeError:
            pass
        except Exception:
            return False
    try:
        if arg is None:
            return target.evaluate(js)
        return target.evaluate(js, arg)
    except Exception:
        return False


def read_text(target) -> str:
    """读页面/iframe 的正文文本（带超时保护）。

    注意：``wait_for_function`` 返回的是 **JSHandle**（不是 dict / str），
    直接 isinstance 判断会永远拿到空字符串 —— 页面文本读不出来，
    状态判定就全部失灵。所以这里要把 JSHandle 取值（json_value）。
    """
    fn = getattr(target, "wait_for_function", None)
    if fn is not None:
        try:
            handle = fn("()=>({t:(document.body && document.body.innerText) || ''})",
                        timeout=5000)
            value = handle
            for getter in ("json_value", "evaluate"):
                fn_getter = getattr(handle, getter, None)
                if fn_getter is None:
                    continue
                try:
                    value = fn_getter() if getter == "json_value" else fn_getter(
                        "e => e && e.t ? e.t : ''")
                    break
                except Exception:
                    continue
            if isinstance(value, dict):
                return value.get("t", "") or ""
            if isinstance(value, str):
                return value
            return ""
        except AttributeError:
            pass
        except Exception:
            return ""
    try:
        return target.evaluate(
            "()=>(document.body && document.body.innerText) || ''") or ""
    except Exception:
        return ""


def fill_controlled(page, js_finder: str, value: str) -> bool:
    """填受控输入框：先 focus/select，再用键盘 insertText（Vue 组件只认真实输入）。

    js_finder 是返回目标元素（或 undefined）的 JS 表达式。
    """
    try:
        handle = page.evaluate_handle(js_finder)
        el = handle.as_element()
        if el is None:
            return False
        el.evaluate("e => { e.focus(); e.select(); }")
    except Exception:
        return False
    time.sleep(0.3)
    page.keyboard.insert_text(value)
    time.sleep(0.5)
    try:
        cur = el.evaluate("e => e.value")
    except Exception:
        return False
    return str(cur).strip() == value.strip()


def set_native(page, js_finder: str, value: str) -> bool:
    """用原生 setter 赋值并派发 input/change（非 Vue 受控控件用）。"""
    js = """
    (arg)=>{
      try{
        const e = (%s);
        if(!e) return 'NO_EL';
        e.focus(); e.select();
        const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(e, arg.v);
        e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true}));
        return e.value;
      }catch(err){ return 'ERR:'+err.message; }
    }
    """ % js_finder
    try:
        r = page.evaluate(js, {"v": value})
    except Exception:
        return False
    return bool(r) and str(r).strip() == value.strip()


def click_by_text(page, text: str, exact: bool = True, scope: str = "") -> bool:
    """按文字点击元素（JS click，绕开遮挡层）。

    **只点最内层的那一个**：页面上常有「按钮 + 包住它的容器 div」，
    容器 div 的 innerText 同样包含按钮文字，按文档顺序先命中容器，
    点它等于没点（典型症状：验证码识别填入后「提交」没反应）。
    所以命中后会把「还包含别的命中元素」的容器剔掉，只点真正那个叶子节点。
    """
    js = """
    (arg)=>{
      const {text, exact, scope} = arg;
      const root = scope ? document.querySelector(scope) : document;
      if(!root) return 'NO_SCOPE';
      const els=[...root.querySelectorAll('a,button,li,span,div,input[type=submit],input[type=button]')];
      const hits=els.filter(e=>{
        const t=(e.innerText||e.value||'').replace(/\\s+/g,'').trim();
        if(!t) return false;
        return exact ? t===text.replace(/\\s+/g,'') : t.indexOf(text.replace(/\\s+/g,''))>=0;
      });
      if(!hits.length) return 'NONE';
      const leaves=hits.filter(e=>!hits.some(o=>o!==e && e.contains(o)));
      const hit=leaves[0]||hits[0];
      hit.click();
      return 'CLICK:'+(hit.innerText||hit.value||'').trim().slice(0,20);
    }
    """
    try:
        r = page.evaluate(js, {"text": text, "exact": exact, "scope": scope})
    except Exception:
        return False
    return isinstance(r, str) and r.startswith("CLICK")


def wait_text(page, pattern: str, timeout: int = 40) -> bool:
    """等待页面上出现匹配正则的文本。"""
    try:
        page.wait_for_function(
            "p => { const b = document.body ? (document.body.innerText||'') : ''; return new RegExp(p).test(b); }",
            arg=pattern, timeout=timeout * 1000,
        )
        return True
    except Exception:
        return False


def wait_ready(page, js: str, timeout: int = 30, interval: float = 1.0,
               should_stop: Optional[Callable[[], None]] = None) -> bool:
    """轮询一个返回 bool 的 JS 表达式。

    should_stop：可选回调（引擎传 check_stop），
    轮询过程中用户点了【中止】就立刻抛异常，不用等满 timeout。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        _raise_if_stopped(should_stop)
        try:
            if page.evaluate(js):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def eval_retry(page, js, arg=None, tries: int = 6, delay: float = 1.5):
    """page.evaluate 的容错版：页面跳转时上下文会被销毁，自动重试。

    gsxt / 住建部等站点在加载中会有一次重定向，此时 evaluate 会抛
    「Execution context was destroyed」，直接返回 None 会让流程误判失败。
    """
    last = None
    for _ in range(tries):
        try:
            if arg is None:
                return page.evaluate(js)
            return page.evaluate(js, arg)
        except Exception as exc:
            last = exc
            time.sleep(delay)
    if last is not None:
        raise last
    return None


def _raise_if_stopped(should_stop: Optional[Callable[[], None]]) -> None:
    """等待轮询过程中若用户中止了，立即抛出。"""
    if should_stop is not None:
        should_stop()
