# -*- coding: utf-8 -*-
"""住建部 —— 住房和城乡建设部：企业资质资格、不良行为、黑名单记录、失信联合惩戒记录。

本模块只包含「这个站点怎么查」的知识；
浏览器、页面动作、截图这些通用能力在 core 包里。
所有方法体都是原 engine.py 逐字搬迁，只改了 self 引用的归属。
"""
from __future__ import annotations

import time, json

from core.errors import EngineError
from core.page import (click_by_text, eval_retry, fill_controlled,
                     set_native, wait_text)
from core import nav
from config import HOME_URLS, MODE_PERSON
from core.errors import Aborted, EngineError, Skipped
from core.result import StepResult
from core.subject import safe_name
from typing import List
from core.capture import dismiss_site_dialogs
from platforms.base import PlatformHandler


# ---- 本平台的选择器/状态判定脚本 ----

MOHURD_STATE_JS = """
(()=>{
  const body=document.body.innerText||'';
  const panes=[...document.querySelectorAll('.el-tab-pane')]
    .filter(p=>getComputedStyle(p).display!=='none');
  const pane=panes[panes.length-1]||document;
  const rows=pane.querySelectorAll('.el-table__body tbody tr').length;
  const emptyEl=pane.querySelector('.el-table__empty-text');
  const empty=!!(emptyEl && getComputedStyle(emptyEl).display!=='none');
  const mask=pane.querySelector('.el-loading-mask');
  const loading=!!(mask && getComputedStyle(mask).display!=='none');
  const totalEl=pane.querySelector('.el-pagination__total');
  const total=totalEl?(totalEl.innerText||'').trim():'';
  const active=(document.querySelector('.el-tabs__item.is-active')||{}).innerText||'';
  return {rows:rows, total:total, empty:empty, loading:loading,
          active:active.trim(), url:location.href,
          snippet:body.replace(/\\n+/g,' | ').slice(0,240)};
})()
"""


class MohurdHandler(PlatformHandler):
    """住建部 的采集处理器。"""

    def collect_group(self, page, company: str, gsteps: list,
                      results: List[StepResult], shots: List[str]) -> None:
        """住建部：一次搜索进入详情页，然后逐个 tab 截图。"""
        try:
            self.search(page, company)
        except Aborted:
            raise
        except Exception as exc:
            self.engine.log("  ✘ 搜索失败：%s" % str(exc).splitlines()[0])
            for step in gsteps:
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          False, message=str(exc)))
            return
        detail = self.open_detail(page, company)
        if detail is None:
            # 检查是否为「非建筑企业/无资质记录」
            st = self.read_state(page)
            rows = int(st.get("rows") or 0)
            empty = bool(st.get("empty")) or rows == 0
            msg = "该主体非建筑企业，在住建部平台未收录建筑企业资质记录" if empty else "未找到匹配的企业名称（非建筑工程企业）"
            self.engine.log("  ⓘ %s" % msg)
            self.engine.log("  → 对当前搜索结果页面留存截图并标记为无记录，继续执行后续步骤")
            try:
                # 截一张无数据的搜索结果页面作为证据存证
                for si, step in enumerate(gsteps):
                    t0 = time.time()
                    if si == 0:
                        path = self.engine.shot_step(page, company, step)
                        shots.append(path)
                        results.append(StepResult(step["no"], step["key"], step["title"], company,
                                                  True, path=path, elapsed=time.time() - t0,
                                                  message="未收录建筑企业资质（无记录）"))
                    else:
                        results.append(StepResult(step["no"], step["key"], step["title"], company,
                                                  True, path=shots[0] if shots else "",
                                                  elapsed=time.time() - t0,
                                                  message="未收录建筑企业资质（无记录）"))
            except Exception as exc:
                for step in gsteps:
                    results.append(StepResult(step["no"], step["key"], step["title"], company,
                                              False, message=msg))
            return
        self.ensure_data(detail, company)
        for si, step in enumerate(gsteps):
            t0 = time.time()
            try:
                # 节流与停止检查都要放在 try 里：
                # 否则【跳过此步】会冒泡出去把整组 4 项一起跳掉。
                if si > 0:
                    self.engine.pace("（下一采集项前）")
                self.engine.check_stop()
                self.engine.log("[%s] %s" % (step["no"], step["title"]))
                ok = self.switch_tab(detail, step["tab"])
                if not ok:
                    self.engine.log("  ！tab「%s」表格未稳定，按当前画面截图" % step["tab"])
                path = self.engine.shot_step(detail, company, step)
                shots.append(path)
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          True, path=path, elapsed=time.time() - t0))
            except Skipped:
                self.engine.log("  ⤼ 本步已跳过")
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          False, message="已跳过"))
            except Aborted:
                raise
            except Exception as exc:
                self.engine.log("  ✘ 失败：%s" % str(exc).splitlines()[0])
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          False, message=str(exc), elapsed=time.time() - t0))

    def search(self, page, company: str):
        """住建部：上级目录跳转 -> 建设工程企业 -> 搜索 -> 结果列表。"""
        self._mohurd_company = company
        self.engine.log("打开住建部：%s" % HOME_URLS["mohurd"])
        # 走统一导航层：从上级目录跳转进入，不直接输入网址
        res = nav.goto_via_landing(page, "mohurd", log=self.engine.log,
                                  timeout_ms=self.engine.timeout * 1000)
        if not res.get("ok"):
            self.engine.log("  ⚠ 上级目录跳转未成功，直接打开目标页")
            nav.goto(page, HOME_URLS["mohurd"], timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log, referer=nav.site_referer("mohurd"))
        if res.get("page") is not None:
            page = res["page"]
        self.engine.sleep(3.0)
        page.evaluate("()=>{const t=[...document.querySelectorAll('.search-tabs__item')]"
                      ".find(e=>e.innerText.trim()==='建设工程企业'); if(t) t.click();}")
        self.engine.sleep(1.5)
        ok = fill_controlled(page, "()=>document.querySelector('.el-input__inner')", company)
        if not ok:
            ok = set_native(page, "()=>document.querySelector('.el-input__inner')", company)
        if not ok:
            raise EngineError("住建部搜索框定位/填入失败")
        page.evaluate("()=>{const b=document.getElementById('query-btn'); if(b) b.click();}")
        self.engine.sleep(6.0)
        page.evaluate("()=>{const s=[...document.querySelectorAll('.ssButton')]"
                      ".find(e=>e.innerText.trim()==='查询'); if(s) s.click();}")
        self.engine.sleep(4.0)
        st = self.wait_stable(page)
        self.engine.log("  列表 total=%s rows=%s" % (st.get("total"), st.get("rows")))
        return st

    def wait_stable(self, page, timeout: int = 40) -> dict:
        """等住建部结果列表稳定下来。

        实测踩坑：点「查询」后表格会经历一次重排（分页 total 还没更新，
        显示「共0条」，但 tbody 里已经有 1 行）。这个中间态里链接的
        getBoundingClientRect() 坐标是**即将失效的旧坐标**（y=472），
        稳定后才是真坐标（y=590）—— 用中间态坐标去点击会点空，
        详情页打不开，12-15 四项全部无产出。

        稳定判据（同时满足）：
          1) loading 遮罩消失；
          2) 分页 total 条数与 tbody 行数一致（都是 0 也算稳定=无结果）；
          3) 目标链接的坐标连续两次采样完全一致。
        """
        deadline = time.time() + timeout
        last_rect = None
        same = 0
        best = {}
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                st = self.read_state(page)
            except Exception:
                self.engine.sleep(0.5)
                continue
            best = st or best
            loading = bool(st.get("loading"))
            total = (st.get("total") or "").strip()
            rows = int(st.get("rows") or 0)
            # 从「共N条」里解析条数
            n = -1
            if "共" in total and "条" in total:
                digits = "".join(ch for ch in total if ch.isdigit())
                if digits:
                    n = int(digits)
            consistent = (n < 0) or (n == rows)

            # 目标链接坐标采样
            try:
                rect = page.evaluate("""
                (arg)=>{
                  const c=[...document.querySelectorAll('.el-table__body tbody tr .link')]
                    .filter(e=>(e.innerText||'').includes(arg.name));
                  const vis=c.filter(e=>{
                    if(e.offsetParent===null) return false;
                    const r=e.getBoundingClientRect();
                    return r.width>0 && r.height>0;
                  });
                  const e=vis[0]||c[0];
                  if(!e) return '';
                  const r=e.getBoundingClientRect();
                  return Math.round(r.x)+','+Math.round(r.y)+','+Math.round(r.width);
                }""", {"name": self._mohurd_company})
            except Exception:
                rect = ""

            if not loading and consistent and rect and rect == last_rect:
                same += 1
                if same >= 2:                       # 连续 2 次一致才算稳
                    return st
            else:
                same = 0
            last_rect = rect
            self.engine.sleep(0.6)

        self.engine.log("  ⚠ 列表未在 %ds 内稳定，按当前状态继续" % timeout)
        return best

    def open_detail(self, page, company: str, attempts: int = 3):
        """点企业名进入详情页（真实鼠标事件，Vue 委托处理），返回详情页对象。

        注意：Element UI 会把所有 tab 的表格都留在 DOM 里，直接用 locator 会命中
        隐藏表格里的同名链接（不可见 -> scroll_into_view 超时）。
        这里先用 JS 挑出「可见」的那一条，滚动稳定后再测坐标，最后用真实鼠标点击。

        点击失败会重试：表格可能仍在重排，此时测到的坐标会失效，
        重新测一次坐标再点即可（最多 attempts 次）。
        """
        for attempt in range(1, attempts + 1):
            r = self.click_detail_once(page, company, attempt)
            if r is not None:
                return r
            if attempt < attempts:
                self.engine.log("  ↻ 详情页未打开，重试点击（第 %d 次）" % (attempt + 1))
                self.engine.sleep(2.0)
        return None

    def click_detail_once(self, page, company: str, attempt: int):
        """点一次企业名链接，返回详情页对象；失败返回 None。"""
        found = page.evaluate("""
        (arg)=>{
          const cands=[...document.querySelectorAll('.el-table__body tbody tr .link')]
            .filter(e=>(e.innerText||'').includes(arg.name));
          if(!cands.length) return 'NONE';
          const vis=cands.filter(e=>{
            if(e.offsetParent===null) return false;
            const r=e.getBoundingClientRect();
            return r.width>0 && r.height>0;
          });
          const e=vis[0]||cands[0];
          e.scrollIntoView({block:'center'});
          return (vis.length?'VISIBLE':'HIDDEN')+':'+(e.innerText||'').trim().slice(0,30);
        }""", {"name": company})
        self.engine.log("  企业名链接：%s" % found)
        if str(found).startswith("NONE"):
            return None
        self.engine.sleep(1.2)

        rc = page.evaluate("""
        (arg)=>{
          const cands=[...document.querySelectorAll('.el-table__body tbody tr .link')]
            .filter(e=>(e.innerText||'').includes(arg.name));
          const vis=cands.filter(e=>{
            if(e.offsetParent===null) return false;
            const r=e.getBoundingClientRect();
            return r.width>0 && r.height>0;
          });
          const e=vis[0]||cands[0];
          if(!e) return 'NONE';
          const r=e.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
        }""", {"name": company})
        if not str(rc).startswith("{"):
            self.engine.log("  详情链接坐标获取失败：%s" % rc)
            return None
        pos = json.loads(rc)
        self.engine.log("  点击坐标=(%s,%s)" % (pos["x"], pos["y"]))
        try:
            page.evaluate("""
            ()=>{
              window.__hits=[];
              ['mousedown','mouseup','click'].forEach(t=>{
                document.addEventListener(t,(ev)=>{
                  const tg=ev.target;
                  window.__hits.push(t+'|'+(tg&&tg.tagName)+'|'+(tg&&(tg.className||'').toString().slice(0,20)));
                }, true);
              });
              const orig=window.open;
              window.open=function(u){ window.__hits.push('window.open|'+u); return orig.apply(window, arguments); };
            }""")
        except Exception:
            pass
        try:
            page.mouse.move(pos["x"], pos["y"])
            self.engine.sleep(0.25)
            page.mouse.down()
            self.engine.sleep(0.25)
            page.mouse.up()
        except Exception as exc:
            self.engine.log("  鼠标点击失败：%s" % str(exc).splitlines()[0])
            return None
        self.engine.sleep(2.0)
        hits = ""
        try:
            hits = page.evaluate("()=>JSON.stringify(window.__hits||[])") or ""
        except Exception:
            pass
        if "window.open" not in hits and "click" not in hits:
            self.engine.log("  事件轨迹异常：%s" % hits[:200])

        deadline = time.time() + 20
        while time.time() < deadline:
            # 不能用 id() 比较新旧标签页：Playwright 每次访问 context.pages 都会新建
            # Page 包装对象，旧对象被 GC 后 id 会被复用，导致新标签页被误判为"旧页"。
            # 直接按详情页 URL 判定最稳。
            #
            # 取上下文用 page.context（每个 Page 自带），
            # 不要用 self.engine.ctx —— 引擎没启动浏览器时它是 None，
            # 而且引擎层的属性变化会让平台模块跟着变脆。
            for p in self.pages_of(page):
                if "company/detail" in (p.url or ""):
                    try:
                        p.wait_for_load_state("domcontentloaded", timeout=20000)
                    except Exception:
                        pass
                    self.engine.sleep(2.5)
                    self.engine.log("  已进入企业详情页")
                    return p
            if "company/detail" in (page.url or ""):
                self.engine.sleep(2.5)
                self.engine.log("  已进入企业详情页")
                return page
            self.engine.sleep(1.0)
        self.engine.log("  未打开企业详情页")
        return None

    @staticmethod
    def pages_of(page):
        """当前浏览器里的全部标签页。"""
        try:
            ctx = page.context
        except Exception:
            ctx = None
        if ctx is None:
            return []
        try:
            return list(ctx.pages)
        except Exception:
            return []

    def ensure_data(self, page, company: str) -> bool:
        """确保详情页已加载出企业数据。

        住建部会话验证有时效，过期时详情页字段全是「--」、表格「暂无数据」，
        并弹「验证已过期，是否重新进行验证或停留在当前页面？」。
        处理顺序：点「重新验证」-> 刷新详情页 -> 仍无数据则请人工完成验证。
        """
        def has_data() -> bool:
            try:
                r = page.evaluate("""
                ()=>{
                  const b=document.body.innerText||'';
                  return /统一社会信用代码[\\s\\S]{0,40}?\\d{15,20}/.test(b);
                }""")
            except Exception:
                return False
            return bool(r)

        if has_data():
            return True

        r = dismiss_site_dialogs(page, prefer="重新验证")
        self.engine.log("  详情数据为空，触发重新验证：%s" % r)
        self.engine.sleep(3)
        try:
            page.reload(wait_until="domcontentloaded", timeout=self.engine.timeout * 1000)
        except Exception:
            pass
        self.engine.sleep(4)
        if has_data():
            self.engine.log("  重新验证后数据已加载")
            return True

        self.engine.wait_manual(
            "住建部企业详情数据为空（会话验证已过期）。请在浏览器里完成住建部验证"
            "（扫码或滑块），完成后点【我已处理，继续截图】。")
        try:
            page.reload(wait_until="domcontentloaded", timeout=self.engine.timeout * 1000)
        except Exception:
            pass
        self.engine.sleep(4)
        ok = has_data()
        self.engine.log("  人工验证后数据加载：%s" % ok)
        return ok

    def switch_tab(self, page, label: str) -> bool:
        """切换详情页 tab 并等表格稳定。

        先 JS click（Element UI 的 tab 支持），失败再回退真实鼠标点击。
        判定「切过去了」要看目标 tab 自己有没有 is-active，而不是取全局第一个
        （页面上可能有多组 el-tabs）。
        """
        page.evaluate("""
        (arg)=>{
          const e=[...document.querySelectorAll('.el-tabs__item')]
            .find(x=>x.innerText.trim()===arg.label);
          if(!e) return 'NOT_FOUND';
          e.click(); return 'JS_CLICK';
        }""", {"label": label})
        self.engine.sleep(2.5)
        if self.tab_active(page, label):
            return self.wait_table(page, label)

        # 回退：真实鼠标点击（滚动稳定后重新测量坐标）
        pos = page.evaluate("""
        (arg)=>{
          const e=[...document.querySelectorAll('.el-tabs__item')]
            .find(x=>x.innerText.trim()===arg.label);
          if(!e) return 'NONE';
          e.scrollIntoView({block:'center'});
          const r=e.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
        }""", {"label": label})
        if not str(pos).startswith("{"):
            self.engine.log("  tab「%s」定位失败" % label)
            return False
        p = json.loads(pos)
        try:
            page.mouse.move(p["x"], p["y"])
            self.engine.sleep(0.3)
            page.mouse.down()
            self.engine.sleep(0.3)
            page.mouse.up()
        except Exception as exc:
            self.engine.log("  tab「%s」点击失败：%s" % (label, str(exc).splitlines()[0]))
            return False
        self.engine.sleep(2.5)
        if not self.tab_active(page, label):
            self.engine.log("  tab「%s」未能激活" % label)
            return False
        return self.wait_table(page, label)

    def tab_active(self, page, label: str) -> bool:
        try:
            r = page.evaluate("""
            (arg)=>{
              const e=[...document.querySelectorAll('.el-tabs__item')]
                .find(x=>x.innerText.trim()===arg.label);
              return !!(e && e.classList.contains('is-active'));
            }""", {"label": label})
        except Exception:
            return False
        return bool(r)

    def wait_table(self, page, label: str) -> bool:
        """等当前可见面板的表格/空态稳定（loading 遮罩消失）。"""
        deadline = time.time() + 45
        while time.time() < deadline:
            self.engine.check_stop()
            st = self.read_state(page)
            if not st.get("loading") and (st.get("rows", 0) > 0 or st.get("empty")):
                self.engine.log("  tab「%s」表格已就绪 total=%s rows=%s"
                         % (label, st.get("total"), st.get("rows")))
                return True
            self.engine.sleep(1.5)
        self.engine.log("  tab「%s」表格未在超时内就绪" % label)
        return False

    def read_state(self, page) -> dict:
        try:
            r = page.evaluate(MOHURD_STATE_JS)
        except Exception:
            return {}
        return r if isinstance(r, dict) else {}
