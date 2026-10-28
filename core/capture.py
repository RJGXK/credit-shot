# -*- coding: utf-8 -*-
"""core/capture.py —— 截图与合成。

四种出图方式都在这里落地：
  原图                     = 浏览器原生整页截图
  原图+信息条              = 往页面里插一条由页面自身渲染的条，再整页截图
  原图+日期弹窗            = 整页截图 + 合成真实屏幕上的 Windows 日期面板
  原图+日期弹窗+信息条      = 上面两种叠加

「信息条」四项内容由用户指定：平台/系统名称及 URL、单位名称、查询日期、查询页面。
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Optional

import desktop
from config import DATE_POPUP_MODES, INFO_BAR_MODES
from core.page import click_by_text

__all__ = [
    "insert_info_bar", "remove_info_bar", "unstick_page", "restick_page",
    "shot_element_by_title", "capture", "compose_date_panel",
    "dismiss_site_dialogs", "unit_label_for_bar",
]


def unit_label_for_bar(company: str, subject=None) -> str:
    """信息条里的「单位名称」：人员模式下写成「姓名（身份证号：xxx）」。"""
    if subject is not None and getattr(subject, "mode", "") == "person":
        return "%s（身份证号：%s）" % (subject.person or "-", subject.idcard or "-")
    return company


def insert_info_bar(page, company: str, step: dict, subject=None,
                     log=print) -> None:
    """在页面顶部插入信息条（由页面自身渲染，随原生整页截图一起入画）。

    信息条内容（用户要求）：
      平台/系统名称及网址（URL）· 单位名称 · 查询日期 · 查询页面
    """
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    platform = step.get("platform") or step.get("site") or ""
    purl = step.get("platform_url") or step.get("url") or ""
    js = """
    (arg)=>{
      const old=document.getElementById('__credit_shot_bar');
      if(old) old.remove();
      const bar=document.createElement('div');
      bar.id='__credit_shot_bar';
      bar.style.cssText='position:relative;z-index:2147483647;box-sizing:border-box;width:100%;'
        +'padding:12px 20px;background:linear-gradient(180deg,#124a9b 0%,#0b3a80 100%);'
        +'color:#fff;border-bottom:3px solid #0a2f66;'
        +'font:14px/1.75 "Microsoft YaHei UI","Microsoft YaHei",sans-serif;'
        +'display:flex;flex-wrap:wrap;gap:6px 30px;align-items:center;';
      const cell=(k,v,opts)=>{
        opts=opts||{};
        const s=document.createElement('span');
        s.style.cssText='display:inline-flex;align-items:baseline;gap:7px;'
          +'max-width:100%;';
        const kb=document.createElement('b');
        kb.textContent=k;
        kb.style.cssText='font-weight:normal;opacity:.75;white-space:nowrap;';
        const vv=document.createElement('span');
        vv.textContent=String(v==null?'':v);
        vv.style.cssText=(opts.small?'font-size:12.5px;opacity:.92;':'')
          +'word-break:break-all;';
        s.appendChild(kb); s.appendChild(vv);
        return s;
      };
      // 平台/系统名称 + 网址
      const p=document.createElement('span');
      p.style.cssText='display:inline-flex;align-items:baseline;gap:7px;max-width:100%;';
      const pn=document.createElement('b');
      pn.textContent=arg.platform;
      pn.style.cssText='font-size:15px;font-weight:600;';
      const pu=document.createElement('span');
      pu.textContent=arg.url;
      pu.style.cssText='font-size:12.5px;opacity:.85;word-break:break-all;';
      p.appendChild(pn); p.appendChild(pu);
      bar.appendChild(p);
      bar.appendChild(cell('单位名称', arg.unit));
      bar.appendChild(cell('查询日期', arg.stamp));
      bar.appendChild(cell('查询页面', arg.page));
      document.body.insertBefore(bar, document.body.firstChild);
      window.scrollTo(0,0);
      return 'OK';
    }
    """
    unit = unit_label_for_bar(company, subject)
    try:
        page.evaluate(js, {"platform": platform, "url": purl,
                           "unit": unit, "stamp": stamp,
                           "page": step["title"]})
        time.sleep(0.6)
    except Exception as exc:
        log("  信息条插入失败：%s" % exc)


def remove_info_bar(page) -> None:
    try:
        page.evaluate("()=>{const b=document.getElementById('__credit_shot_bar'); if(b) b.remove();}")
    except Exception:
        pass


def unstick_page(page) -> None:
    """把页面里的 sticky / fixed 元素临时改成 static。

    gsxt 详情页左侧目录导航是 sticky 定位，顶部栏是 fixed。
    Playwright 展开整页截图时会反复滚动拼接，sticky 元素会导致整页截图一直等不到稳定 → 超时。
    改成 static 后整页图里左侧导航也完整出现，正好符合需要。
    """
    try:
        page.evaluate("""
        ()=>{
          window.__credit_shot_sticky = [];
          for (const el of document.querySelectorAll('body *')){
            const pos = getComputedStyle(el).position;
            if (pos === 'sticky' || pos === 'fixed'){
              window.__credit_shot_sticky.push([el, el.style.position]);
              el.style.position = 'static';
            }
          }
          return window.__credit_shot_sticky.length;
        }""")
    except Exception:
        pass


def restick_page(page) -> None:
    try:
        page.evaluate("""
        ()=>{
          const list = window.__credit_shot_sticky || [];
          for (const [el, pos] of list) { el.style.position = pos; }
          window.__credit_shot_sticky = [];
        }""")
    except Exception:
        pass


def shot_element_by_title(page, path: str, title: str,
                           log=print) -> bool:
    """按板块标题裁剪截图（视口坐标 clip）。

    gsxt 详情页是单页长滚动，「严重违法失信名单」这类靠后的板块滚不到视口顶部，
    整页截图四张又完全一样。这里先定位「标题 + 表格」所在容器，
    把它滚动到视口中间，再用视口坐标 clip 精确裁出这一块。

    为什么不用 full_page + clip：详情页左侧目录是 sticky 定位，
    Playwright 展开整页时会反复滚动拼接，sticky 元素导致整页截图超时。

    返回是否截图成功。
    """
    find_js = """
    (arg)=>{
      const norm=s=>(s||'').replace(/\\s+/g,'');
      const W=window.innerWidth;
      const hits=[...document.querySelectorAll('h1,h2,h3,h4,div,span,p,strong')]
        .filter(e=>{
          const t=norm(e.innerText||e.textContent||'');
          if(!t || t.length>arg.kw.length+14) return false;
          return t===arg.kw || t.startsWith(arg.kw);
        })
        .filter(e=>e.getBoundingClientRect().x >= W*0.12);   // 排除左侧目录里的同名项
      if(!hits.length) return null;
      hits.sort((a,b)=>norm(a.innerText||a.textContent||'').length
                        -norm(b.innerText||b.textContent||'').length);
      const titleEl=hits[0];
      // 向上找第一个「含表格」的祖先，作为整个板块的容器
      let el=titleEl;
      for(let i=0;i<8 && el;i++){
        if(el.querySelector && el.querySelector('table')) break;
        el=el.parentElement;
      }
      if(!el) el=titleEl;
      return el;
    }
    """
    try:
        # 1) 先把板块容器滚到视口中间
        page.evaluate("""(arg)=>{
          const norm=s=>(s||'').replace(/\\s+/g,'');
          const W=window.innerWidth;
          const hits=[...document.querySelectorAll('h1,h2,h3,h4,div,span,p,strong')]
            .filter(e=>{const t=norm(e.innerText||e.textContent||'');
                        return t && t.length<=arg.kw.length+14
                          && (t===arg.kw||t.startsWith(arg.kw));})
            .filter(e=>e.getBoundingClientRect().x >= W*0.12);
          if(!hits.length) return;
          hits.sort((a,b)=>norm(a.innerText||a.textContent||'').length
                            -norm(b.innerText||b.textContent||'').length);
          let el=hits[0];
          for(let i=0;i<8 && el;i++){
            if(el.querySelector && el.querySelector('table')) break;
            el=el.parentElement;
          }
          if(el) el.scrollIntoView({block:'center'});
        }""", {"kw": title})
        time.sleep(0.9)

        # 2) 取视口坐标并裁剪
        box = page.evaluate("""(arg)=>{
          const norm=s=>(s||'').replace(/\\s+/g,'');
          const W=window.innerWidth;
          const hits=[...document.querySelectorAll('h1,h2,h3,h4,div,span,p,strong')]
            .filter(e=>{const t=norm(e.innerText||e.textContent||'');
                        return t && t.length<=arg.kw.length+14
                          && (t===arg.kw||t.startsWith(arg.kw));})
            .filter(e=>e.getBoundingClientRect().x >= W*0.12);
          if(!hits.length) return null;
          hits.sort((a,b)=>norm(a.innerText||a.textContent||'').length
                            -norm(b.innerText||b.textContent||'').length);
          let el=hits[0];
          for(let i=0;i<8 && el;i++){
            if(el.querySelector && el.querySelector('table')) break;
            el=el.parentElement;
          }
          if(!el) return null;
          const r=el.getBoundingClientRect();
          const vh=window.innerHeight, vw=window.innerWidth;
          return {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width),
                  h:Math.round(r.height), vh, vw,
                  inView: r.top>=0 && r.bottom<=vh && r.left>=0 && r.right<=vw};
        }""", {"kw": title})
        if not box:
            return False
        if not box.get("inView"):
            log("  板块比视口高，改用可视区截图")
            return False
        page.screenshot(path=path, full_page=False, timeout=60000,
                        clip={"x": max(0, int(box["x"])), "y": max(0, int(box["y"])),
                              "width": max(1, int(box["w"])), "height": max(1, int(box["h"]))})
        return True
    except Exception as exc:
        log("  板块裁剪截图失败(%s)，退回可视区截图" % str(exc).splitlines()[0])
        return False


def _shrink_page_for_shot(page) -> None:
    """把页面整体缩小，让整页截图更快更稳。

    超长页面（gsxt 详情页、住建部长表格）用 ``full_page=True`` 截图时，
    Playwright 要按视口高度反复滚动拼接，容易撞到 90 秒超时。
    把 body 缩到 50% 之后，页面总高度减半，拼接次数少一半，截图快得多；
    文字略小但内容完整，事后可以再放大看。
    """
    try:
        page.evaluate("""()=>{
          if(document.documentElement.style.zoom) return;
          document.documentElement.style.zoom='0.5';
        }""")
    except Exception:
        pass


def _restore_page_zoom(page) -> None:
    try:
        page.evaluate("()=>{document.documentElement.style.zoom='';}")
    except Exception:
        pass


def _screenshot_with_fallback(page, path: str, log, full_page: bool,
                              timeout_ms: int = 90000) -> None:
    """截图，失败时逐级降级并重试。

    降级顺序：
      1. 原生整页截图（用户要求页面完整，用 page.screenshot(full_page=True)）
      2. 解除 sticky/fixed + 页面缩到 50% 后再整页截图
      3. 视口截图（保证至少有一张图，不让整条采集项失败）

    用户反馈「截图失败」——多半是整页拼接超时，这里把它兜住。
    """
    try:
        page.screenshot(path=path, full_page=full_page, timeout=timeout_ms)
        return
    except Exception as exc:
        log("  ⚠ 整页截图失败(%s)，尝试降级方案" % str(exc).splitlines()[0][:80])

    if full_page:
        # 降级 1：解除 sticky + 缩放后重试整页
        unstick_page(page)
        _shrink_page_for_shot(page)
        time.sleep(1.2)
        try:
            page.screenshot(path=path, full_page=True, timeout=timeout_ms)
            log("  ✔ 缩放后整页截图成功")
            _restore_page_zoom(page)
            return
        except Exception as exc:
            log("  ⚠ 缩放整页仍失败(%s)，退回可视区截图"
                % str(exc).splitlines()[0][:70])
        _restore_page_zoom(page)

    # 降级 2：视口截图
    try:
        page.screenshot(path=path, full_page=False, timeout=60000)
        log("  ✔ 已保存（可视区截图）")
        return
    except Exception as exc:
        raise RuntimeError("截图失败：%s" % str(exc).splitlines()[0])


def capture(page, path: str, company: str, step: dict, shot_mode: str,
             subject=None, log=print) -> str:
    """截图。

    「原图 / 原图+信息条」= 浏览器原生整页截图（page.screenshot(full_page=True)），
    页面内容完整；信息条是往页面里插一条由页面自己渲染的条。

    「原图+日期弹窗 / 原图+日期弹窗+信息条」= 同样是页面完整整页图，
    再把 Windows 右下角的系统日期/时间面板合成到图片右下角
    （面板本身用真实屏幕抓取——浏览器原生截图画不出系统浮层）。

    步骤带 viewport_shot 时改用**可视区截图**（不滚到顶、不整页）：
    gsxt 详情页是单页长滚动，基础信息 / 行政处罚 / 经营异常 / 严重违法失信
    四个板块依次排列，整页截图会四张一模一样，只有可视区才能区分板块。
    """
    # 先关掉站点自己弹的浮层（如住建部「验证已过期」），否则会挡住截图内容
    dismiss_site_dialogs(page)
    viewport_only = bool(step.get("viewport_shot"))
    unstick = bool(step.get("unstick"))
    if not viewport_only:
        try:
            page.evaluate("()=>window.scrollTo(0,0)")
            time.sleep(0.4)
        except Exception:
            pass
    want_bar = shot_mode in INFO_BAR_MODES
    if want_bar:
        insert_info_bar(page, company, step)
    if unstick:
        unstick_page(page)
    try:
        if viewport_only and step.get("section"):
            # 板块类采集项：按「标题 + 表格」所在容器做元素级截图
            if not shot_element_by_title(page, path, step["section"]):
                _screenshot_with_fallback(page, path, log, full_page=False)
        elif viewport_only:
            _screenshot_with_fallback(page, path, log, full_page=False)
        else:
            _screenshot_with_fallback(page, path, log, full_page=True)
    finally:
        if unstick:
            restick_page(page)
        remove_info_bar(page)

    if shot_mode in DATE_POPUP_MODES:
        compose_date_panel(path)
    return path


def compose_date_panel(path: str, log=print) -> None:
    """把系统日期/时间面板合成到已截好的页面原图右下角。

    合成失败时保留原图（不丢内容），只在日志里提示。
    """
    panel_path = ""
    try:
        panel_path = os.path.join(os.path.dirname(path), "_date_panel.png")
        got = desktop.grab_date_panel(panel_path, log)
        if not got:
            return
        from PIL import Image, ImageDraw, ImageFilter

        _ppath, _rect, k = got
        orig = Image.open(path).convert("RGB")
        panel = Image.open(panel_path).convert("RGBA")

        margin = max(12, int(round(14 * k)))
        x = orig.width - panel.width - margin
        y = orig.height - panel.height - margin
        if x < 0:
            # 原图比面板还窄：放到右下角并允许贴边
            x = max(0, orig.width - panel.width)
        if y < 0:
            y = max(0, orig.height - panel.height)

        # 面板投影，让它看起来像浮在页面上
        shadow = Image.new("RGBA", panel.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([0, 0, panel.width - 1, panel.height - 1],
                                         fill=(0, 0, 0, 110))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(4, int(6 * k))))
        base = orig.convert("RGBA")
        base.alpha_composite(shadow, (x + int(4 * k), y + int(5 * k)))
        base.alpha_composite(panel, (x, y))
        base.convert("RGB").save(path)
        log("  ✔ 已叠加日期/时间面板（%dx%d，缩放 %.0f%%，位于右下角）"
                 % (panel.width, panel.height, k * 100))
    except Exception as exc:
        log("  ⚠ 日期面板合成失败，保留页面原图：%s" % exc)
    finally:
        try:
            if panel_path and os.path.exists(panel_path):
                os.remove(panel_path)
        except Exception:
            pass


def bring_browser_to_front(page, log=print) -> None:
    """把浏览器窗口提到前台。

    日期/时间面板是**系统浮层**：只有浏览器窗口在前台时它才会显示在
    浏览器之上、才能被整屏截图抓到。浏览器在后台时，面板会被别的窗口
    挡住 —— 这正是用户反馈「有些不能弹出日期详情」的原因之一。
    """
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        hwnd = desktop.find_browser_window("Edge", "")
        if hwnd:
            desktop.activate_window(hwnd, maximize=False)
            time.sleep(0.5)
    except Exception:
        pass


def dismiss_site_dialogs(page, prefer: str = "停留在当前页") -> str:
    """关掉站点弹的浮层（Element UI 确认框 / 通用对话框）。

    住建部会话过期会弹「验证已过期，是否重新重新进行验证或停留在当前页面？」，
    按钮文字实测为「重新验证」「停留在当前页」，不关掉会盖住整页截图。

    注意：这类遮罩是 position:fixed，offsetParent 为 null，不能用它判可见性，
    要用 getClientRects().length。
    """
    js = """
    (arg)=>{
      try{
        const vis=e=>{
          if(!e) return false;
          const s=getComputedStyle(e);
          if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity||'1')===0) return false;
          return e.getClientRects().length>0;
        };
        const boxes=[...document.querySelectorAll(
          '.el-message-box__wrapper, .el-message-box, .el-dialog__wrapper, .el-overlay')]
          .filter(vis);
        let scope=boxes.length?boxes:[document];
        for(const sc of scope){
          const btns=[...sc.querySelectorAll('button, .el-button, a.btn, a')]
            .filter(vis);
          let t=btns.find(x=>(x.innerText||'').trim().indexOf(arg.prefer)>=0);
          if(!t) t=btns.find(x=>/取消|关闭|知道了|稍后再说|留在当前/.test((x.innerText||'').trim()));
          if(t){ t.click(); return 'CLICK:'+(t.innerText||'').trim().slice(0,12); }
        }
        return boxes.length?('NO_BTN:'+boxes.length):'NONE';
      }catch(e){ return 'ERR:'+e.message; }
    }
    """
    try:
        r = page.evaluate(js, {"prefer": prefer})
    except Exception:
        return "NONE"
    if isinstance(r, str) and r.startswith("CLICK"):
        time.sleep(1.8)
        try:
            page.evaluate("()=>window.scrollTo(0,0)")
        except Exception:
            pass
    return r if isinstance(r, str) else "NONE"
