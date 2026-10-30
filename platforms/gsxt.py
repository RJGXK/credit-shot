# -*- coding: utf-8 -*-
"""国家企业信用信息公示系统 —— 国家企业信用信息公示系统：基础信息（含股东出资）、行政处罚、经营异常、严重违法失信（黑名单）等板块。

本模块只包含「这个站点怎么查」的知识；
浏览器、页面动作、截图这些通用能力在 core 包里。
所有方法体都是原 engine.py 逐字搬迁，只改了 self 引用的归属。
"""
from __future__ import annotations

import json
import time

from core.errors import EngineError
from core.page import (click_by_text, eval_retry, fill_controlled,
                     set_native, wait_text, type_human)
from core import nav
from config import HOME_URLS, MODE_PERSON
from core.errors import Aborted, EngineError, Skipped
from core.result import StepResult
from core.subject import safe_name
from typing import List
from platforms.base import PlatformHandler


class GsxtHandler(PlatformHandler):
    """国家企业信用信息公示系统 的采集处理器。"""

    def reset_subject_state(self) -> None:
        """换查询主体时清掉 gsxt 的会话状态。

        不清的话第二个主体会沿用第一个主体的「已在详情页」标记，
        直接跳过搜索，结果就串了。
        """
        self._gsxt_in_detail = False
        self._gsxt_page = None
        self._gsxt_logged_in = False
        self._gsxt_ip_blocked = False

    def _walk_detail_sidebar(self, page) -> int:
        """详情页左侧「目录导航」逐级展开并点击，触发所有板块的懒加载。

        用户要求「所有信息」都要截到：侧边栏**大项**展开 → **小分项** → 详情。
        站点 SPA 里多数板块是「点目录项才渲染/才显示」的，不点开整页截图就会缺内容。

        实现：每轮先收集左侧导航里所有可点击条目标题（大项与小分项），点掉一个未见过的，
        再重新收集（点开大项后小分项才出现），如此反复直到全部点过或达上限。
        纯防御：任一环节失败都不抛，只记录；最后滚回顶部。返回实际点击条数。
        """
        try:
            has_nav = page.evaluate("""()=>{
              const norm=s=>(s||'').replace(/\\s+/g,'').trim();
              return [...document.querySelectorAll('div,span,h1,h2,h3,p,a,label')]
                .some(e=>norm(e.innerText||e.textContent||'')==='目录导航');
            }""")
        except Exception:
            has_nav = False
        if not has_nav:
            self.engine.log("  ⚠ 未找到「目录导航」，跳过侧边栏遍历")
            return 0

        def _collect():
            try:
                return page.evaluate("""()=>{
                  const W=window.innerWidth;
                  const norm=s=>(s||'').replace(/\\s+/g,'').trim();
                  const t=[...document.querySelectorAll('div,span,h1,h2,h3,p,a,label')]
                    .find(e=>norm(e.innerText||e.textContent||'')==='目录导航');
                  if(!t) return [];
                  let root=t;
                  for(let i=0;i<7 && root.parentElement;i++){root=root.parentElement;
                    if(root.querySelectorAll('a,li,span,div').length>=8) break;}
                  return [...root.querySelectorAll('a,span,div,li,em,i,label')]
                    .filter(e=>{const r=e.getBoundingClientRect();
                      if(r.width<=0||r.height<=0) return false;
                      if(r.x>=W*0.35) return false;     // 只取左侧导航
                      const tx=norm(e.innerText||e.textContent||'');
                      return tx && tx.length<30 && tx!=='目录导航';})
                    .map(e=>norm(e.innerText||e.textContent||''));
                }""")
            except Exception:
                return []

        def _click_one(kw):
            # 关键（v2.2.7）：小分项也要用**真实鼠标点击**。v2.2.4 已实锤
            # 「人点就灵、软件合成 .click() 被吞」，入口和登录都是这个根因，
            # 侧边栏小分项同理——只展开不点开就看不到具体详情（用户反馈第 2 点）。
            js = """
            (kw)=>{
              const W=window.innerWidth;
              const norm=s=>(s||'').replace(/\\s+/g,'').trim();
              const t=[...document.querySelectorAll('div,span,h1,h2,h3,p,a,label')]
                .find(e=>norm(e.innerText||e.textContent||'')==='目录导航');
              if(!t) return '';
              let root=t;
              for(let i=0;i<7 && root.parentElement;i++){root=root.parentElement;
                if(root.querySelectorAll('a,li,span,div').length>=8) break;}
              const els=[...root.querySelectorAll('a,span,div,li,em,i,label')]
                .filter(e=>{const r=e.getBoundingClientRect();
                  return r.width>0&&r.height>0&&r.x<W*0.35&&
                    norm(e.innerText||e.textContent||'')===kw;});
              if(!els.length) return '';
              els.sort((a,b)=>norm(a.innerText||a.textContent||'').length
                              -norm(b.innerText||b.textContent||'').length);
              const e=els[0];
              e.scrollIntoView({block:'center'});
              const b=e.getBoundingClientRect();
              return JSON.stringify({cx:b.left+b.width/2, cy:b.top+b.height/2,
                                     tag:e.tagName});
            }"""
            try:
                r = page.evaluate(js, kw)
                data = json.loads(r) if isinstance(r, str) and r.startswith("{") else None
            except Exception as exc:
                data = None
                return "ERR:%s" % str(exc).splitlines()[0][:40]
            if not data:
                return ""
            try:
                page.mouse.click(data["cx"], data["cy"])
                return "CLICK:" + kw
            except Exception:
                # 真实点击失败（元素被遮挡等）才回落合成点击
                try:
                    page.evaluate("""(kw)=>{
                      const W=window.innerWidth;
                      const norm=s=>(s||'').replace(/\\s+/g,'').trim();
                      const t=[...document.querySelectorAll('div,span,h1,h2,h3,p,a,label')]
                        .find(e=>norm(e.innerText||e.textContent||'')==='目录导航');
                      if(!t) return;
                      let root=t;
                      for(let i=0;i<7 && root.parentElement;i++){root=root.parentElement;
                        if(root.querySelectorAll('a,li,span,div').length>=8) break;}
                      const els=[...root.querySelectorAll('a,span,div,li,em,i,label')]
                        .filter(e=>{const r2=e.getBoundingClientRect();
                          return r2.width>0&&r2.height>0&&r2.x<W*0.35&&
                            norm(e.innerText||e.textContent||'')===kw;});
                      if(els.length) els[0].click();
                    }""", kw)
                    return "CLICK:" + kw
                except Exception as exc:
                    return "ERR:%s" % str(exc).splitlines()[0][:40]

        seen = set()
        clicked = 0
        MAX = 24
        for _ in range(MAX + 6):
            items = _collect()
            target = None
            for it in items:
                if it and it not in seen:
                    target = it
                    break
            if target is None:
                break
            seen.add(target)
            r = _click_one(target)
            if str(r).startswith("CLICK"):
                clicked += 1
                self.engine.log("  侧边栏展开/点击：%s" % target)
            self.engine.sleep(0.7)
        # 遍历完滚回顶部，避免最后停留位置影响整页截图
        try:
            page.evaluate("()=>window.scrollTo(0,0)")
        except Exception:
            pass
        return clicked

    def collect_group(self, page, company: str, gsteps: list,
                            results: List[StepResult], shots: List[str]) -> None:
        """gsxt 企业详情页组：**合成一张整页图**。

        用户要求「行政处罚信息 / 列入经营异常名录信息 / 列入严重违法失信名单（黑名单）信息」
        与「基础信息（含全部股东及出资详细信息）」**截在同一张图里**，
        所以这里只截一次整页图，组内各采集项共用这一张。

        整页截图前要先把页面里 sticky / fixed 的元素（左侧目录导航、顶部栏）改成 static，
        否则 Playwright 展开整页时反复滚动拼接，sticky 元素会让整页截图超时。
        """
        try:
            self.enter_detail(page, company)
        except (Aborted, Skipped):
            raise
        except Exception as exc:
            self.engine.log("  ✘ 进入企业详情页失败：%s" % str(exc).splitlines()[0])
        # 上级目录跳转可能开了新标签页，后续截图要用那个页面；
        # 旧页可能已被标签清理关掉 → 必须解析出活页，否则截图也崩
        page = getattr(self, "_gsxt_page", None) or page
        page = self._live_page(page) or page
        if self._browser_dead():
            self.engine.log("  ✘ 浏览器已被关闭，本组无法继续（请检查浏览器窗口）")
            raise EngineError("浏览器已被关闭")
        self.engine.log("  本组截图所用页面：%s" % (page.url or "<未知>")[:90])

        # 展开「全部股东及出资详细信息」
        expanded = page.evaluate("""
        ()=>{
          const cands=[...document.querySelectorAll('a,span,div,button')]
            .filter(e=>/全部股东|股东及出资详细信息|查看全部/.test((e.innerText||'').trim()));
          if(!cands.length) return 'NONE';
          const e=cands[0];
          e.scrollIntoView({block:'center'});
          e.click();
          return 'CLICK:'+(e.innerText||'').trim().slice(0,24);
        }""")
        self.engine.log("  展开股东详细信息：%s" % expanded)
        self.engine.sleep(2.5)

        # 点一下左侧「违法失信信息」下的板块，让这部分显示出来（用户指定的位置）
        for step in gsteps:
            kw = (step.get("section") or "").strip()
            if not kw:
                continue
            r = self.click_left_nav(page, kw)
            if str(r).startswith("CLICK"):
                self.engine.log("  左侧目录「%s」：%s" % (kw, r))
            self.engine.sleep(1.2)

        # 逐级展开侧边栏（大项→小分项），触发所有板块的懒加载，
        # 这样「所有信息」都能进入 DOM 被整页截到（用户要求）。
        n = self._walk_detail_sidebar(page)
        self.engine.log("  侧边栏逐级展开完成，共点击 %d 项" % n)
        self.engine.sleep(1.5)

        # 详情页板块内容是**滚动懒加载**：没滚到过的板块 DOM 里是空的，
        # 整页截图时那些板块就缺失了（用户实测「四个板块没法同时展示」）。
        # 所以截图前把页面从头到尾滚一遍触发全部加载，再回到顶部。
        self.engine.log("  滚动触发全部板块加载…")
        page.evaluate("""()=>{
          window.__csScrollStep = 0;
          const step = () => {
            window.scrollBy(0, Math.round(window.innerHeight * 0.8));
            window.__csScrollStep += 1;
            if (window.__csScrollStep < 40 &&
                window.scrollY + window.innerHeight < document.body.scrollHeight - 4) {
              setTimeout(step, 220);
            } else {
              window.scrollTo(0, 0);
            }
          };
          step();
        }""")
        self.engine.sleep(4.0)   # 等滚动完成 + 异步内容渲染

        shared = ""
        for step in gsteps:
            t0 = time.time()
            try:
                # 这一组共用同一张整页图，跳过就是整组一起跳
                self.engine.check_stop()
                self.engine.log("[%s] %s" % (step["no"], step["title"]))
                if not shared:
                    # 无论由哪一项负责截图，都必须解除 sticky，否则整页截图会超时
                    shot_step = dict(step)
                    shot_step["unstick"] = True
                    shared = self.engine.shot_step(page, company, shot_step)
                    shots.append(shared)
                results.append(StepResult(step["no"], step["key"], step["title"], company, True,
                                          path=shared, elapsed=time.time() - t0,
                                          message="已并入同一张详情页整页图"))
            except Skipped:
                self.engine.log("  ⤼ 本步已跳过")
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          False, message="已跳过"))
            except Aborted:
                raise
        self.engine.log("  ✔ 四个板块（基础信息 / 行政处罚 / 经营异常 / 严重违法失信）合并为一张：%s" % shared)

    def open_portal(self, page, rounds: int = 3) -> bool:
        """打开 gsxt 首页并等到可操作，返回是否成功就绪。

        实测踩坑（两条，都很致命）：

        1) **直连必被拦**。``https://www.gsxt.gov.cn/index.html`` 直连会返回
           瑞数的 521「Environment Checking」挑战页（白页），
           浏览器里要等挑战脚本跑完才放行；而且部分情况下会判定「异常 IP」。
           用户实测确认：必须**从其他页面跳转**进来。
           所以这里走 core.nav 的入口链：
               国家市场监督管理总局 → 点「国家企业信用信息公示系统」→ gsxt
           站内点击产生的导航自带 Referer，最不容易被判异常。

        2) gsxt 首页会先跳到「Loading https://www.gsxt.gov.cn/index.html」
           再重定向回真正首页，这段跳转期间调用 page.evaluate 会抛
           「Execution context was destroyed」。而且 title 在跳转前后分别是
           '' 和 '国家企业信用信息公示系统'，光看 title 判断不了「能用」。

        所以这里改成等**搜索框 #keyword 真正可见**才算就绪。
        """
        # ---- 走上级目录跳转链 ----
        # **不要裸跳**：从登录子站/空白页直接 goto gsxt 首页属于「无来源直达」，
        # 瑞数会把这套会话判成异常（页面能开，但点【查询】毫无反应，
        # 刷新后提示「当前IP请求异常 / 您的IP最近有可疑的攻击行为」）。
        # 一律从市场监管总局点链接进来，导航天然带 Referer。
        # 入口救援：调用方传进来的 page 可能已被上一轮的标签页清理关掉
        # （18:04 日志实锤：黑名单组拿到已关的主页 → 全链 Target page closed）。
        lp = self._live_page(page)
        if lp is not None and lp is not page:
            self.engine.log("  ⓘ 原标签页已关闭，改用现存标签页继续")
            page = lp
        chain_res = nav.goto_via_landing(page, "gsxt", log=self.engine.log,
                                         timeout_ms=self.engine.timeout * 1000)
        # 链接带 target=_blank 时会开新标签页，后续操作要切过去。
        # 这里把新页面记到实例上，调用方按需取用（page 形参改不了）。
        newp = chain_res.get("page")
        if newp is not None:
            self._gsxt_page = newp
            self.engine.log("  已切换到 gsxt 新标签页")
        # 后续所有等待/操作都打在**实际生效的那个页面**上
        page = self._gsxt_page or page
        cleared_once = False
        for rnd in range(1, rounds + 1):
            # 浏览器被用户关掉了 → 立即止损，别再重试（否则一秒刷五条
            # 「Target page has been closed」，用户日志 14:03:25 就是它）
            if self._browser_dead():
                self.engine.log("  ✘ 浏览器已被关闭，停止导航重试")
                return False
            # IP 被风控时首页根本出不来（点查询也只会毫无反应）：
            # 必须立刻停手，反复重走入口链只会被判得更死。
            if self._detect_ip_blocked(page):
                self._gsxt_ip_blocked = True
                self._log_ip_blocked()
                return False
            ok = self.wait_keyword(page, timeout=18)
            if ok:
                # 校验这次进入到底有没有携带上个网站的信息（Referer）。
                # 空来源最容易触发风控：宁可再走一次入口链，也别带着异常会话去查询。
                ref = ""
                try:
                    ref = str(page.evaluate("()=>document.referrer||''"))
                except Exception:
                    pass
                self.engine.log("  进入首页携带的来源：%s" % (ref[:100] or "（空）"))
                if not ref and rnd < rounds:
                    self.engine.log("  ⚠ 本次进入没有携带上个网站信息，容易触发风控，"
                                    "重新从上级目录进入")
                    try:
                        c3 = nav.goto_via_landing(page, "gsxt", log=self.engine.log,
                                                  timeout_ms=self.engine.timeout * 1000)
                        if c3.get("page") is not None:
                            self._gsxt_page = c3["page"]
                            page = self._gsxt_page
                    except Exception:
                        pass
                    self.engine.sleep(2.5)
                    continue
                if rnd > 1 or chain_res.get("via"):
                    self.engine.log("  gsxt 首页就绪（第 %d 次尝试）" % rnd)
                # 就绪后把多余的旧标签页清掉（搜索页/上次残留），
                # 用户反馈「页面打开太多，不知道软件在操作哪个」——
                # 之后浏览器里只剩这一个工作页，人工配合时看它就对了。
                self._close_extra_tabs(page)
                return True
            if self._detect_ip_blocked(page):
                self._gsxt_ip_blocked = True
                self._log_ip_blocked()
                return False
            # 静默 400/白页也要兜住：站点判废票据时不一定给提示文案，
            # 有时就是一张空白页（HTTP 400 + 无正文）。
            # 但要区分两种「没读出来」：
            #   · nav_state 返回空 dict（evaluate 抛异常）→ 多半是页面正在做瑞数
            #     重定向挑战、执行上下文被打掉（复用旧进程时常见），这不算「空白页」，
            #     别急着清票据（清了反而可能把刚拿到的会话冲掉），直接重走入口链即可；
            #   · 真有正文但太短 / 被判拒绝 → 才是旧票据判废，清票据重试。
            # 两种情况都只在首次出现时清一次，避免每轮都清、把会话越清越死。
            st = nav.nav_state(page)
            genuine_blank = bool(st) and "len" in st and not st.get("checking") \
                and (st.get("blank") or st.get("len", 0) < 60)
            unhealthy = not bool(st)  # evaluate 抛异常：页面不可读
            if (genuine_blank or unhealthy) and not cleared_once:
                if genuine_blank:
                    self.engine.log("  ⚠ 首页空白/被拒（可能旧会话票据被判废），清票据后重试")
                else:
                    self.engine.log("  ⚠ 首页读取异常（页面可能正在做环境挑战），清票据后重试")
                self._clear_site_cookies(page)
                cleared_once = True
                self.engine.sleep(1.5)
                # 不 continue：让下面的「重走入口链」分支把页面重新带起来
            if rnd < rounds:
                if self._browser_dead():
                    self.engine.log("  ✘ 浏览器已被关闭，停止导航重试")
                    return False
                self.engine.log("  gsxt 首页未就绪，重新通过上级目录跳转进入（第 %d 次）" % (rnd + 1))
                old_page = page
                try:
                    c2 = nav.goto_via_landing(page, "gsxt", log=self.engine.log,
                                              timeout_ms=self.engine.timeout * 1000)
                    if c2.get("page") is not None:
                        self._gsxt_page = c2["page"]
                        page = self._gsxt_page
                        # 新工作页到手就关掉上一轮的旧 gsxt 标签页，防止越积越多
                        if page is not old_page:
                            try:
                                old_page.close()
                            except Exception:
                                pass
                except Exception as exc:
                    self.engine.log("  gsxt 重新跳转异常(第%d次)：%s"
                             % (rnd, str(exc).splitlines()[0][:60]))
                self.engine.sleep(3.0)
        # 最后再试一次入口链（第一次可能是瑞数挑战没过）
        if not chain_res.get("ok"):
            self.engine.log("  提示：gsxt 环境校验较慢，继续尝试")
        return False

    def _detect_ip_blocked(self, page) -> bool:
        """判断当前页是不是「IP 被风控 / 会话票据被判废」的拒绝页。

        实测文案（2026-10-30）：
          当前IP请求异常，请更换IP地址进行访问，或访问地址
          （https://shiming.gsxt.gov.cn）实名注册/登录后再进行访问…
          error: 您的IP最近有可疑的攻击行为，请稍后重试.
        另有一类直接是 **HTTP 400 Bad Request**（用户抓包实锤：响应头带
        x-via-jsl，请求带着旧的 __jsl_clearance_s / SECTOKEN / CT_* 票据
        被加速乐判废；此时页面正文可能很短甚至为空，只靠文案会漏判）。
        判据：① 页面文案；② 关键判废票据仍在 + 正文异常短（400 的典型形态）。
        """
        try:
            lp = self._live_page(page)
            if lp is None:
                return False
            r = lp.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              const bad=/当前IP请求异常|可疑的攻击行为|更换IP地址/.test(b)
                     || /400 Bad Request/i.test(b);
              return {bad:bad, len:(b||'').length,
                      snippet:b.replace(/\\s+/g,' ').slice(0,160)};
            }""")
        except Exception:
            return False
        if r and r.get("bad"):
            self.engine.log("  ⚠ 命中公示系统拒绝页：%s" % str(r.get("snippet"))[:120])
            return True
        # 400 判废的静默形态：正文异常短 + 票据还在
        if r is not None and r.get("len", 999) <= 40:
            try:
                cks = lp.context.cookies(urls=["https://www.gsxt.gov.cn"])
                names = [str(c.get("name") or "") for c in cks]
                stale = [n for n in ("__jsl_clearance_s", "SECTOKEN", "__jsluid_s")
                         if n in names]
                if stale:
                    self.engine.log("  ⚠ 疑似 HTTP 400 判废：正文仅 %d 字符，"
                                    "且旧票据仍在（%s）"
                                    % (r.get("len", 0), "、".join(stale)))
                    return True
            except Exception:
                pass
        return False

    def _clear_site_cookies(self, page, origins=None) -> bool:
        """清掉公示系统的旧会话票据（加速乐 __jsl_clearance_s / 瑞数 SECTOKEN 等）。

        为什么要清：软件用的是**专用浏览器资料目录**，票据会一直留着。
        一旦 WAF 把那套票据判废（换 IP、长时间闲置、自动化行为被判可疑），
        之后每个请求都 400 —— 表现就是「页面打不开 / 点查询毫无反应」，
        而用户自己的浏览器没有这套脏票据，一切正常。
        按站点清（不清全库），避免把裁判文书网的登录态一起丢掉。

        v2.2.9 修正（用户抓包实锤 400 + 18:04:28「清理失败」）：
          · 传入的 page 可能已死 → **先解析引擎活页**再清理，
            否则 CDP 会话建不起来、清理静默失败、旧票据一直在、反复 400；
          · 清理后**回读 Cookie 核对**，把关键票据（__jsluid_s/__jsl_clearance_s/
            SECTOKEN/JSESSIONID）是否真被清掉写进日志——给排查留确凿证据。
        """
        origins = origins or ["https://www.gsxt.gov.cn",
                              "https://gsxt.gov.cn",
                              "https://shiming.gsxt.gov.cn",
                              "http://www.gsxt.gov.cn"]
        # 传入页可能已死：优先解析活页，退而求其次用引擎主页
        lp = self._live_page(page)
        if lp is None:
            try:
                eng = getattr(self.engine, "browser_session", None)
                cand = getattr(eng, "page", None)
                if cand is not None and not cand.is_closed():
                    lp = cand
            except Exception:
                lp = None
        if lp is None:
            self.engine.log("  ⚠ 清理失败：浏览器里没有可用标签页，无法执行清理")
            return False

        def _snap():
            try:
                cks = lp.context.cookies(urls=["https://www.gsxt.gov.cn",
                                               "https://shiming.gsxt.gov.cn"])
                return [str(c.get("name") or "") for c in cks]
            except Exception:
                return []

        key_tickets = ("__jsluid_s", "__jsl_clearance_s", "SECTOKEN", "JSESSIONID")
        before = _snap()
        targets = [c for c in before if c in key_tickets]

        cleared = False
        try:
            cdp = lp.context.new_cdp_session(lp)
            for origin in origins:
                try:
                    cdp.send("Storage.clearDataForOrigin",
                             {"origin": origin,
                              "storageTypes": "cookies,local_storage,session_storage"})
                    cleared = True
                except Exception:
                    continue
            try:
                cdp.detach()
            except Exception:
                pass
        except Exception:
            pass
        if not cleared:
            # 拿不到 CDP 会话时退化为清全部 Cookie：会连带丢掉裁判文书网登录态
            # （下次会自动重新登录），但总比一直 400 强。
            try:
                lp.context.clear_cookies()
                cleared = True
                self.engine.log("  ⚠ 按站点清理不可用，已清空全部 Cookie"
                                "（裁判文书网登录态会丢，下次自动重登）")
            except Exception:
                pass
        if cleared:
            after = _snap()
            remain = [c for c in targets if c in after]
            if targets:
                self.engine.log("  票据核对：%s %s"
                                % ("、".join(targets),
                                   "已全部清除" if not remain
                                   else "仍有残留（%s）" % "、".join(remain)))
            self.engine.log("  ✔ 已清理 公示系统旧会话票据（按站点，Cookie %d → %d 枚）"
                            % (len(before), len(after)))
        else:
            self.engine.log("  ⚠ 清理失败 公示系统旧会话票据（-）")
        return cleared

    def _log_ip_blocked(self) -> None:
        """把被拒绝的解决路径写清楚（用户看到的排查依据）。"""
        self.engine.log("  ⚠ 公示系统拒绝了本机请求（IP 风控 / 设备票据被判废 / HTTP 400）。")
        self.engine.log("    解决办法：① 换网络/IP（切换热点、代理或重启光猫）；")
        self.engine.log("    ② 在界面把「浏览器」从 Edge 换成 Chrome（或反之）再试 ——")
        self.engine.log("       实测同一台机器：Edge 那份资料被判废时，Chrome 能正常查询；")
        self.engine.log("    ③ 打开 https://shiming.gsxt.gov.cn 实名登录后再查；④ 等一段时间再试。")

    def _resolve_ip_block(self, page):
        """被风控（含 HTTP 400）后的补救：先清票据重试，再实名登录/换 IP。"""
        # 传入页可能已死（上一轮重试换过页）：先解析活页，
        # 否则清票据和后续登录都会静默失败（18:04:28「清理失败」实锤）
        page = self._live_page(page) or page
        # ---- 第一步：清掉判废的会话票据，重走入口链 ----
        self.engine.log("  gsxt 被拒绝（IP 风控 / HTTP 400）：先清掉本站旧票据再试一次")
        self._clear_site_cookies(page)
        self._gsxt_ip_blocked = False
        ok_portal = self.open_portal(page)
        page = getattr(self, "_gsxt_page", None) or page
        if ok_portal and not self._detect_ip_blocked(page):
            self.engine.log("  ✔ 清票据后恢复正常")
            return page

        # ---- 第二步：还是被拦 → 重启浏览器进程（新进程+新票据）再试一次 ----
        # 探针实锤（2026-10-29）：同一套代码+同 Profile，**新进程**搜索链全程正常；
        # 复用旧进程时被加速乐判废的票据/进程内状态会一直 400。
        # 清票据只清了存储，进程内的会话状态还在——重启才能拿到全新票据。
        self.engine.log("  ⚠ 清票据后仍被拦截，重启浏览器进程获取全新票据后再试")
        try:
            bs = getattr(self.engine, "browser_session", None)
            if bs is not None:
                bs.close()
                self.engine.sleep(2.0)
                pw2, b2, ctx2, pg2 = bs.open()
                self.engine.log("  ✔ 浏览器已重启（新进程），重新进入公示系统")
                page = pg2
        except Exception as exc:
            self.engine.log("  ⚠ 重启浏览器失败：%s，改走实名登录通道"
                            % str(exc).splitlines()[0][:60])
            page = self._live_page(page) or page

        # ---- 第三步：重启后仍被拦 → 实名登录 / 换 IP ----
        if self._detect_ip_blocked(page):
            self.engine.log("  ⚠ 重启后仍被拦截，改走实名登录通道（shiming.gsxt.gov.cn）")
            ok = False
            try:
                # ensure_login 内部会自己打开实名认证子站的登录页
                ok = self.ensure_login(page)
            except (Aborted, Skipped):
                raise
            except Exception as exc:
                self.engine.log("  自动登录异常：%s" % str(exc).splitlines()[0][:80])
            if ok:
                self.engine.log("  ✔ 实名登录成功，重新打开公示系统首页")
            else:
                self.engine.wait_manual(
                    "公示系统拒绝了本机请求（「当前IP请求异常 / IP 有可疑攻击行为」或 HTTP 400）。\n"
                    "程序已自动清理过本站旧 Cookie 并重启过浏览器，仍被拦截。请任选其一：\n"
                    "① 换一个网络或 IP（切换热点/代理）后重试；\n"
                    "② 在界面把「浏览器」Edge ↔ Chrome 换一个再试（实测另一浏览器可正常查询）；\n"
                    "③ 在浏览器里打开 https://shiming.gsxt.gov.cn 完成实名登录。\n"
                    "处理好后点【继续】，程序会重新打开首页继续查询。")
        self._gsxt_ip_blocked = False
        self.open_portal(page)
        return getattr(self, "_gsxt_page", None) or page

    def wait_keyword(self, page, timeout: int = 25) -> bool:
        """等 gsxt 搜索框 #keyword 可见。

        顺带处理瑞数的「Environment Checking」挑战页：
        标题是 Environment Checking / 环境检测时，说明还在做环境校验，
        需要多等一会儿让它自动放行。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                ok = page.evaluate(
                    "()=>{const e=document.getElementById('keyword');"
                    "if(!e) return false; const r=e.getBoundingClientRect();"
                    "return r.width>0 && r.height>0;}")
            except Exception:
                # 跳转期间上下文被销毁，属正常情况，继续等
                self.engine.sleep(1.5)
                continue
            if ok:
                return True
            self.engine.sleep(1.5)
        return False

    def ensure_login(self, page) -> bool:
        """gsxt 自动登录（配了账号密码时）。

        登录框在主页面里（``.loginBox``），不是 iframe；
        提交后可能弹极验滑块/点选（打码服务不支持，只能人工）。
        """
        cred = self.engine.credentials.get("gsxt") or {}
        username = (cred.get("username") or "").strip()
        password = cred.get("password") or ""
        if not username or not password:
            return False
        self.engine.log("  尝试自动登录 gsxt…")
        return bool(self.engine.auto_login(page, "gsxt", "国家企业信用信息公示系统"))

    def _live_page(self, page):
        """返回一个还活着的 page 对象，避免重试时拿到已关闭/分离的引用，
        导致整条入口链崩成「Target page, context or browser has been closed」这种
        让人摸不着头脑的总失败（用户日志 15:11/15:12 的结尾就是它）。"""
        try:
            if page is not None and not page.is_closed():
                # 顺手探一下上下文还在不在
                _ = page.context
                return page
        except Exception:
            pass
        try:
            pages = list(page.context.pages)
        except Exception:
            return None
        # 优先返回还停在 gsxt 域的活页
        for p in pages:
            try:
                if not p.is_closed() and "gsxt.gov.cn" in (p.url or ""):
                    return p
            except Exception:
                continue
        for p in pages:
            try:
                if not p.is_closed():
                    return p
            except Exception:
                continue
        return None

    def _browser_dead(self) -> bool:
        """整个浏览器上下文是否已不可用（用户手动关了浏览器窗口等）。

        返回 True 时调用方必须立即止损——再重试只会刷屏
        「Target page, context or browser has been closed」。
        """
        try:
            ctx = self.engine.ctx
            if ctx is None:
                return True
            _ = list(ctx.pages)
            return False
        except Exception:
            return True

    def _close_extra_tabs(self, keep, log_prefix: str = "  清理多余标签页") -> int:
        """关掉除 keep 以外的所有标签页（用户反馈「页面打开太多，不知道在操作哪个」）。

        **保护名单（v2.2.8 教训）**：除了 keep，还必须保住——
          · 引擎当前持有的 page（browser_session.open() 返回的那个）：
            18:04 日志实锤，把它关掉后后续所有采集组全链
            「Target page, context or browser has been closed」；
          · 初始 about:blank 主页：引擎重启后第一个 tab，关掉等于砍断根。
        返回关闭个数。纯防御：任何一步失败都不抛。
        """
        closed = 0
        try:
            if keep is None or keep.is_closed():
                return 0
            ctx = keep.context
            # 引擎主页：browser_session.page（connect_cdp 记录的那个）
            # 被清理误杀后，后续所有采集组全链 Target page closed（18:04 日志实锤）
            engine_pages = set()
            eng_page = getattr(getattr(self.engine, "browser_session", None),
                               "page", None)
            if eng_page is not None:
                engine_pages.add(id(eng_page))
            for p in list(ctx.pages):
                if p is keep:
                    continue
                try:
                    if p.is_closed():
                        continue
                    # 保护：引擎当前持有的 page 不能关（它是后续采集组的操作根）
                    if id(p) in engine_pages:
                        continue
                    p.close()
                    closed += 1
                except Exception:
                    continue
            if closed:
                self.engine.log("%s：已关闭 %d 个旧标签页，当前只保留 gsxt 工作页"
                                % (log_prefix, closed))
            try:
                keep.bring_to_front()
            except Exception:
                pass
        except Exception:
            pass
        return closed

    def _gsxt_is_logged_in(self, page) -> bool:
        """首页上是否已处于登录态：出现「退出登录/个人中心/欢迎您」等字样即视为已登录。

        软件浏览器复用同一份资料目录，登录态会落在 cookie 里持久化，
        所以第二次运行（或同一次运行内后续主体）常常已经登录，不必再走一遍登录。
        """
        try:
            return bool(page.evaluate("""()=>{
              const t=(document.body&&document.body.innerText)||'';
              if(/退出登录|个人中心|欢迎您|已登录|用户中心|我的关注/.test(t)) return true;
              return false;
            }"""))
        except Exception:
            return False

    def _after_login_enter(self, page):
        """登录后重新进入首页搜索框（登录成功会整页跳回首页）。"""
        try:
            lp = self._live_page(page) or page
            self.open_portal(lp)
            return getattr(self, "_gsxt_page", None) or lp
        except Exception as exc:
            self.engine.log("  ⚠ 登录后重新进入首页失败：%s"
                            % str(exc).splitlines()[0][:60])
            return page

    def _login_succeeded(self, page) -> bool:
        """登录是否真正成功：页面上出现「退出登录/个人中心/欢迎您」等登录态标志。

        **v2.2.8 修正**：旧版用「URL 在 gsxt 域且不在 shiming 子站」就算成功——
        但匿名首页同样满足这个条件（18:00:24 日志实锤：明明没登录却报
        「当前已是登录态，跳过自动登录」，导致登录通道被永远跳过）。
        URL 启发式必须废除，只认页面上的登录态标志。
        """
        return self._gsxt_is_logged_in(page)

    def _try_login_first(self, page):
        """登录（仅在匿名搜索被拦时才调用）：先自动填+过码，没成则交用户手动登录。

        关键修正（v2.2.4→v2.2.6）：
          · 用户反馈「账号密码手动输入可以登录，但软件自动登录一直弹验证码」——
            软件浏览器极易被极验反复挑战，自动过码常过不去。于是这里**绝不软件自动死循环弹码**，
            自动没过就交用户手动登录（用户已确认手动可用），并做成功回检。
          · 手动兜底是有界重试（最多 3 次 wait_manual），每次点【继续】后回检
            是否真的登录成功；不像旧版那样无限循环弹验证码。
        """
        # 已经登录（同进程内前面已登录过 / 资料目录里带着登录态）→ 直接跳过
        # 注意：只用「页面上有退出登录等标志」判断，不用 URL 启发式
        # （匿名首页也在 gsxt 域，URL 判定会误报已登录 → 登录通道被跳过）
        if getattr(self, "_gsxt_logged_in", False) or self._gsxt_is_logged_in(page):
            self.engine.log("  gsxt：当前已是登录态，跳过自动登录")
            self._gsxt_logged_in = True
            return page
        self.engine.log("  gsxt：匿名搜索被拦，尝试登录"
                        "（账号密码程序自动填好，滑块/点选需人工过）")
        ok = False
        try:
            ok = self.ensure_login(page)
        except (Aborted, Skipped):
            raise
        except Exception as exc:
            self.engine.log("  自动登录异常：%s" % str(exc).splitlines()[0][:80])
        if ok:
            self.engine.log("  ✔ gsxt 自动登录成功（已进入登录态）")
            self._gsxt_logged_in = True
            return self._after_login_enter(page)

        # 自动没完成（极验在软件浏览器里常反复挑战）→ 交用户手动登录（有界重试 + 成功回检）
        lp = self._live_page(page) or page
        for attempt in range(1, 4):
            self.engine.wait_manual(
                "gsxt 需要登录才能搜索。\n"
                "账号密码程序已自动填好：请在浏览器里手动完成验证并点【登录】按钮，"
                "登录成功（跳回公示系统首页）后点【继续】。\n"
                "若仍停在登录页，说明验证还没过，请再点一次【登录】或刷新重试。"
                "（你已确认手动输入可以登录）")
            lp = self._live_page(page) or lp
            if self._login_succeeded(lp):
                self.engine.log("  ✔ 检测到已登录（手动）")
                self._gsxt_logged_in = True
                return self._after_login_enter(lp)
            self.engine.log("  ⚠ 仍未检测到登录成功，请再试一次（第 %d 次）" % attempt)
        # 兜底：当作用户已登录继续往下走（搜索可能仍可用，或留在当前页截图）
        self.engine.log("  ⚠ 多次手动登录仍未确认成功，继续尝试搜索（若被拦请换 IP 或手动登录）")
        self._gsxt_logged_in = True
        return self._after_login_enter(self._live_page(page) or page)

    def enter_detail(self, page, company: str) -> bool:
        """gsxt：先登录（配了账号时）→ 搜索企业 → 人工过极验并点选企业 → 切到详情新标签页。

        实测流程（2026-10-29）：
          index 页 #keyword 填名称 → #btn_query → 弹极验 → 列表页
          → 点企业**开新标签页**，先是「Environment Checking」白页，
            约 3 秒后自动变成详情页（含「目录导航」「基础信息」）。

        重要修正（v2.2.3）：早期认为「全程不需要登录」，但 2026-10-29 多版实测证明
        **匿名搜索被 WAF/IP 风控拦截**——点了查询毫无反应，或返回「当前IP请求异常」
        拒绝页（官方提示本身就是「实名注册/登录后再进行访问」）。用户自己的浏览器正是
        **登录态**才正常查询。所以现在：配了账号就**先登录再搜**；只有未配账号时才走匿名。

        Environment Checking 是瑞数挑战页，**只能等，不能刷新**
        （刷新会重新挑战，用户实测「刷新等 5 秒也还是白页」）。
        """
        if getattr(self, "_gsxt_in_detail", False):
            return True
        ok_portal = self.open_portal(page)
        self.engine.log("  入口链结果：ok_portal=%s，_gsxt_ip_blocked=%s"
                        % (ok_portal, getattr(self, "_gsxt_ip_blocked", False)))
        page = getattr(self, "_gsxt_page", None) or page
        # 首页没起来（风控 / 票据判废 / 空白页）都走补救：清票据 → 重进 → 必要时登录
        if not ok_portal or getattr(self, "_gsxt_ip_blocked", False):
            page = self._resolve_ip_block(page)
            if self._detect_ip_blocked(page):
                self.engine.log("  ⚠ 仍然被限制，跳过自动查询（按当前画面截图）")
                return False

        creds = (self.engine.credentials or {}).get("gsxt") or {}
        has_creds = bool(creds.get("username") and creds.get("password"))

        # ① 先**匿名慢速搜索**（登录是整条链路最不稳的一环，能不登录就不登录）。
        #    用户反馈「手动能登、软件死循环」正是因为之前一上来就强制登录。
        self.engine.log("  → 先尝试匿名搜索（慢速输入，避免被风控判机器人）：%s" % company)
        status = self._search_company(page, company)
        self.engine.log("  匿名搜索结果状态：%s" % status)

        # ② 匿名没通过 + 配了账号 + 还没登录 → 才走登录通道，登录后重搜一次。
        #    （匿名 'reacted' 说明已经能搜 / 弹验证码，无需登录；'blocked' 走清票据补救）
        if status in ("login", "none") and has_creds and not getattr(self, "_gsxt_logged_in", False):
            self.engine.log("  匿名搜索未通过，改走登录通道（慢速输入账号密码）后重搜")
            page = self._try_login_first(page)
            page = getattr(self, "_gsxt_page", None) or page
            status = self._search_company(page, company)
            self.engine.log("  登录后搜索结果状态：%s" % status)
        elif status == "blocked":
            # 清掉判废票据再搜一次（不强制登录）
            page = self._resolve_ip_block(page)
            if self._detect_ip_blocked(page):
                self.engine.log("  ⚠ 当前 IP 仍被限制，跳过自动查询（按当前画面截图）")
                return False
            status = self._search_company(page, company)
            if getattr(self, "_gsxt_ip_blocked", False):
                self.engine.log("  ⚠ IP 仍被公示系统限制，停止自动查询")
                return False

        for round_no in range(1, 4):
            # _search_company 内部可能重走入口链换了新页（旧的已关）：
            # 这里必须重新同步活页，否则下面点查询直接崩
            # （18:03:24 日志实锤：拿已关旧页再点 → Target page closed）
            page = getattr(self, "_gsxt_page", None) or page
            page = self._live_page(page) or page
            if self._browser_dead():
                self.engine.log("  ✘ 浏览器已被关闭，停止详情页流程")
                return False
            # 极验可能根本没弹出来（隐藏容器曾导致误判已修，但站点行为会变）：
            # 挂起前先看一眼，没弹就自动**再真实点一次【查询】**，不干等用户。
            if round_no == 1:
                listing_now = False
                gt_now = False
                try:
                    listing_now = bool("/corp-query-search/" in (page.url or ""))
                except Exception:
                    listing_now = False
                try:
                    gt_now = self._geetest_visible_in(page)
                except Exception:
                    gt_now = False
                if not listing_now and not gt_now:
                    self.engine.log("  ⚠ 验证弹层没有出现，自动再点一次【查询】")
                    self._click_query(page)
                    self._wait_search_reaction(page, timeout=8)

            self.engine.wait_manual(
                "gsxt 已搜索「%s」\n"
                "（程序只在标题为「国家企业信用信息公示系统」的那个标签页里操作，"
                "多余的旧标签页已自动关闭）：\n"
                "① 请在浏览器里完成验证码/滑块（极验弹窗可能出现在页面中央或独立浮层，"
                "需要手动拖动/点选）；\n"
                "② 验证通过后会出现企业列表，点目标企业进入详情页"
                "（新标签页先显示 Environment Checking，等几秒自动放行，不要刷新）；\n"
                "③ 若验证码始终不出现，请直接在浏览器里手动点击首页【查询】按钮并拖动滑块，"
                "程序会持续等待直到出现企业列表/详情页。\n"
                "完成后点【继续】；想重来可点【跳过此步】。" % company)
            try:
                pages = list(page.context.pages)
            except Exception:
                pages = [page]
            # 用户可能在等待期间关了浏览器
            if self._browser_dead():
                self.engine.log("  ✘ 浏览器已被关闭，停止等待详情页")
                return False

            # 平台自己跳出了登录页 → 这时才登录，登录后重新搜索
            login_page = self._find_login_page(pages)
            if login_page is not None and self._find_detail_page(pages) is None:
                self.engine.log("  平台要求登录，开始登录")
                ok = False
                try:
                    ok = self.ensure_login(login_page)
                except (Aborted, Skipped):
                    raise
                except Exception as exc:
                    self.engine.log("  自动登录异常：%s" % str(exc).splitlines()[0][:80])
                if not ok:
                    self.engine.wait_manual(
                        "gsxt 需要登录：请在浏览器里手动完成登录，登录成功后点【继续】。")
                self._gsxt_logged_in = True
                self.engine.log("  登录后重新搜索：%s" % company)
                self.open_portal(page)
                page = getattr(self, "_gsxt_page", None) or page
                self._search_company(page, company)
                continue

            detail = self._wait_detail(pages, timeout=60)
            if detail is not None:
                self._gsxt_page = detail
                self._gsxt_in_detail = True
                try:
                    detail.bring_to_front()
                except Exception:
                    pass
                self.engine.log("  ✔ 已进入企业详情页：%s" % (detail.url or "")[:90])
                # 关掉搜索页/搜索引擎页等残留标签：之后人工配合和整页截图
                # 都只在详情页这一个标签上进行（用户反馈「不知道在操作哪个」）
                self._close_extra_tabs(detail, log_prefix="  清理多余标签页")
                return True
            self.engine.log("  ⚠ 还没找到企业详情页（第 %d 次），请确认已点击目标企业" % round_no)
        self.engine.log("  ⚠ 未能进入企业详情页，按当前页面截图")
        return False

    def _search_company(self, page, company: str) -> str:
        """在 gsxt 首页**慢速**输入公司名并点【查询】。返回状态字符串：

          'reacted' —— 已跳到结果页（corp-query-search）或已弹极验
                       （进入 wait_manual 让用户过码 / 点企业即可）
          'login'   —— 点查询后被跳转到登录页（匿名搜索被拦，需要登录）
          'blocked' —— 命中 IP 风控 / 拒绝页（400 / 当前IP请求异常）
          'none'    —— 点了毫无反应（没明确拒绝页、也没跳转）

        关键修复（用户反馈「点了查询没反应 / 登录死循环」）：
          · 公司名用**逐字符慢速输入**（type_human），瞬时灌值会被瑞数/极验
            行为式风控判机器人 → 表现为点了没反应；
          · 返回状态而非布尔，让 enter_detail 决定「先匿名搜、登录作兜底」，
            不再一上来就强制登录（登录是整条链路最不稳的一环）。
        """
        for attempt in range(1, 3):
            # 浏览器被关掉：立即止损（重试只会刷屏 Target page has been closed）
            if self._browser_dead():
                self.engine.log("  ✘ 浏览器已被关闭，停止搜索重试")
                return "none"
            # 查询前先看是不是已经被风控（此时点按钮不会跳转，重试只会更糟）
            if self._detect_ip_blocked(page):
                self._gsxt_ip_blocked = True
                self._log_ip_blocked()
                return "blocked"
            if attempt > 1:
                self.engine.log("  ↻ 搜索没有反应，重走入口链再试（第 %d 轮）" % attempt)
                lp = self._live_page(page) or page
                self.open_portal(lp)
                page = getattr(self, "_gsxt_page", None) or lp
                if self._detect_ip_blocked(page):
                    self._gsxt_ip_blocked = True
                    self._log_ip_blocked()
                    return "blocked"
            self.engine.log("在 gsxt 首页搜索（慢速输入）：%s" % company)
            # 确认现在确实停在 gsxt 首页（而不是卡在 Bing/搜索结果页——
            # 那样点查询当然没反应，必须先回到入口链）
            try:
                cur_url = str(page.evaluate("()=>location.href") or "")
            except Exception:
                cur_url = "<无法读取>"
            self.engine.log("  当前页面：%s" % cur_url[:96])

            # 等页面完全加载（geetest 与站点脚本绑定完再点，否则点了没反应）
            try:
                page.wait_for_function("()=>document.readyState==='complete'",
                                       timeout=15000)
            except Exception:
                pass

            # ---- 填词 + 回读校验（慢速逐字输入，防止「看着填上了其实没写进去」）----
            filled = False
            for fill_attempt in range(1, 4):
                if self._fill_keyword(page, company):
                    readback = ""
                    try:
                        readback = str(page.evaluate(
                            "()=>(document.getElementById('keyword')||{}).value||''"))
                    except Exception:
                        pass
                    if readback.strip() == company.strip():
                        filled = True
                        break
                    self.engine.log("  ⚠ 输入框回读值不匹配（%r），重填（第 %d 次）"
                             % (readback[:20], fill_attempt + 1))
                if fill_attempt < 3:
                    self.engine.sleep(1.2)
            if not filled:
                self.engine.log("  ⚠ 搜索框定位/填入失败，进入下一轮重试")
                continue
            self.engine.sleep(0.8)
            self.engine.log("  填词结果：OK；准备点击【查询】")

            # ---- 点查询 + 验证有反应 ----
            self._click_query(page)
            # 极验弹层常驻独立 iframe，渲染比主页面慢，给足 8s
            if self._wait_search_reaction(page, timeout=8):
                self.engine.log("  ✔ 点查询后有反应（已跳转或已弹验证）")
                return "reacted"
            # 点完没反应：先确认是不是被风控
            if self._detect_ip_blocked(page):
                self._gsxt_ip_blocked = True
                self._log_ip_blocked()
                return "blocked"
            # 被跳到登录页？
            try:
                if self._find_login_page(list(page.context.pages)) is not None:
                    self.engine.log("  ⚠ 点查询后被跳转到登录页（匿名搜索被拦，需要登录）")
                    return "login"
            except Exception:
                pass

            # ---- 回落：输入框回车 / 站内结果页链接 ----
            self.engine.log("  ⚠ 点【查询】后没有跳转，改用输入框回车再试")
            try:
                page.locator("#keyword").first.press("Enter", timeout=4000)
            except Exception:
                pass
            if self._wait_search_reaction(page, timeout=8):
                return "reacted"
            if self._detect_ip_blocked(page):
                self._gsxt_ip_blocked = True
                self._log_ip_blocked()
                return "blocked"
            # 再兜一层：页面里如果本来就有指向结果页的链接，点它最稳
            # （链接自带站点追加的参数，点击产生的导航还带 Referer）
            if self._click_search_link(page):
                if self._wait_search_reaction(page, timeout=8):
                    return "reacted"
                if self._detect_ip_blocked(page):
                    self._gsxt_ip_blocked = True
                    self._log_ip_blocked()
                    return "blocked"

        self.engine.log("  ⚠ 自动搜索始终没有跳转（已重试 2 轮）")
        return "none"

    def _click_search_link(self, page) -> bool:
        """兜底：点页面里指向结果页（corp-query-search）的链接。

        比 JS 点按钮可靠：链接的 href 本身带着站点要求的全部参数，
        点击产生的导航也天然带 Referer（「携带上个网站的信息」）。
        """
        try:
            r = page.evaluate("""()=>{
              const a=[...document.querySelectorAll('a[href]')]
                .find(x=>/corp-query-search/.test(x.href||''));
              if(!a) return 'NONE';
              a.click();
              return 'CLICK:'+(a.href||'').slice(0,90);
            }""")
        except Exception:
            return False
        self.engine.log("  兜底：点击站内结果页链接 %s" % str(r)[:100])
        return str(r).startswith("CLICK")

    def _fill_keyword(self, page, company: str) -> bool:
        """把企业名称填进搜索框。

        用**逐字符真实键盘输入**（type_human，拟人随机间隔）——公司名瞬间灌入会被
        瑞数/极验行为式风控当成机器人，表现为「点了查询没反应 / 被拦」。与登录填值
        同理，慢速手敲才不会被识别。填完回读校验，失败回落原生 setter。
        """
        try:
            val = type_human(page, "() => document.getElementById('keyword')", company)
            if val and val.strip() == company.strip():
                return True
            self.engine.log("  逐字符输入回读不一致（%r），回落原生填值" % (val or "")[:20])
            if fill_controlled(page, "() => document.getElementById('keyword')", company):
                return True
            return bool(set_native(page, "() => document.getElementById('keyword')", company))
        except Exception:
            return False

    def _click_query(self, page) -> str:
        """点【查询】：**优先真实鼠标点击**（浏览器认为可信的事件，站点脚本才响应），
        再退回 JS 点击。gsxt 的按钮 innerText 是空的，必须按 id 找。

        之前只做 JS `btn.click()`：站点若用 jQuery/原生 addEventListener 绑定且
        校验事件可信度，就会「点了没反应」——这正是用户反馈的现象。
        """
        # 先清掉可能挡在前面的弹层
        try:
            page.evaluate("""()=>{
              const closeBtns = [...document.querySelectorAll(
                '.layui-layer-close, .popup-close, .close, [class*=close]')];
              for(const c of closeBtns){
                if(c.offsetWidth > 0 && c.offsetHeight > 0) c.click();
              }
            }""")
        except Exception:
            pass

        # ① 真实鼠标点击
        try:
            loc = page.locator("#btn_query").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            self.engine.log("  触发 gsxt 查询按钮：OK:TRUSTED_CLICK")
            return "OK:TRUSTED_CLICK"
        except Exception:
            pass

        # ② 按坐标点一次（按钮被遮挡时真实点击会失败，坐标点击仍可）
        try:
            box = page.evaluate("""()=>{
              const b=document.getElementById('btn_query')
                   || document.querySelector('.search_btn');
              if(!b) return null;
              const r=b.getBoundingClientRect();
              if(r.width<2 || r.height<2) return null;
              return {x:r.x+r.width/2, y:r.y+r.height/2};
            }""")
            if box:
                page.mouse.click(box["x"], box["y"])
                self.engine.log("  触发 gsxt 查询按钮：OK:MOUSE_CLICK")
                return "OK:MOUSE_CLICK"
        except Exception:
            pass

        # ③ 最后才用 JS 触发
        clicked = page.evaluate("""()=>{
          const btn = document.getElementById('btn_query')
                   || document.querySelector('.search_btn')
                   || [...document.querySelectorAll('button, a, input[type=button], input[type=submit]')]
                      .find(e => /查询|搜索/.test((e.innerText||e.value||e.title||'').trim()));
          if(!btn) return 'NO_BTN';
          btn.focus();
          btn.click();
          return 'OK:' + (btn.id || btn.className || btn.tagName);
        }""")
        if not str(clicked).startswith("OK"):
            click_by_text(page, "查 询", exact=False)
            click_by_text(page, "查询", exact=False)
        self.engine.log("  触发 gsxt 查询按钮：%s" % clicked)
        return str(clicked)

    @staticmethod
    def _geetest_visible_in(frame) -> bool:
        """在单个 frame 里判断 geetest 弹层**真的可见**（不是模板里的隐藏占位）。

        极验的滑块/点选弹层常驻在**独立 iframe**（主页面只留一个隐藏占位容器，
        所以只查主页面会漏判——表现为「点了查询却说没反应」，重新走入口链）。
        这里在每个 frame 内分别查，且放宽阈值（尺寸>50×40、匹配更泛的验证提示、
        或含极验专有结构：图片/滑块/拼图/canvas）。
        """
        try:
            return bool(frame.evaluate("""()=>{
              const sel='.geetest_holder,.geetest_panel,.geetest_window,.geetest_wind,'
                      +'[id*=geetest],[class*=geetest],#popup-captcha,.gt_holder,.gt_popup';
              const els=[...document.querySelectorAll(sel)];
              return els.some(e=>{
                let st=null;
                try{ st=getComputedStyle(e);}catch(err){ return false;}
                if(st.display==='none'||st.visibility==='hidden'||+st.opacity===0) return false;
                const b=e.getBoundingClientRect();
                if(b.width<=50||b.height<=40) return false;
                // 视口内才算弹层（隐藏模板容器常在文档底部量出巨大尺寸）
                const vh=window.innerHeight||3000, vw=window.innerWidth||3000;
                if(b.bottom<0||b.right<0||b.top>vh||b.left>vw) return false;
                const t=(e.innerText||'');
                if(/请点击|请依次|点选|拖动|滑块|完成验证|验证|点击图片|拼图|文字|安全验证/.test(t)) return true;
                if(e.querySelector('img,canvas,.geetest_slider,.geetest_question,.geetest_pic,.gt_slider')) return true;
                // 极验激活时外层常带 geetest_panel/geetest_show 之类可见子类
                return !!e.querySelector('.geetest_panel,.geetest_show,.gt_panel,.gt_show');
              });
            }"""))
        except Exception:
            return False

    def _wait_search_reaction(self, page, timeout: float = 6.0) -> bool:
        """等搜索「有反应」：任一标签页跳到结果页，或验证弹层**真的显示**。

        之前的问题是点完就 blind sleep(3)，跳没跳转完全不知道，
        用户看到的就是「搜了但不动」。

        实测坑（2026-10-30 用户日志）：
        1) 点击同一秒就报「✔ 已触发验证」——根因是主页面那个**隐藏的 geetest
           占位容器**被量出尺寸误判成已弹出（v2.2.0 已修：加 visibility/size 判据）。
        2) 但极验激活时弹层常驻**独立 iframe**，主页面只能看到隐藏占位
           → 又会被判成「没反应」，于是自动重走入口链、用户那边其实弹了却白等。
           现在改成**跨所有 frame** 检测，且阈值放宽（见 _geetest_visible_in）。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                for p in page.context.pages:
                    if "corp-query-search" in (p.url or ""):
                        self.engine.log("  ✔ 已跳转到搜索结果页：%s" % (p.url or "")[:90])
                        if p is not getattr(self, "_gsxt_page", None):
                            self._gsxt_page = p
                        return True
            except Exception:
                pass
            # 跨 frame 检测极验弹层（含极验专属 iframe）
            try:
                frames = list(page.frames)
            except Exception:
                frames = [page]
            for fr in frames:
                if self._geetest_visible_in(fr):
                    self.engine.log("  ✔ 已触发验证（极验/图形验证码）")
                    return True
            self.engine.sleep(0.5)
        return False

    @staticmethod
    def _page_flags(p) -> dict:
        try:
            r = p.evaluate("""()=>{
              const b=(document.body&&document.body.innerText)||'';
              return {url:location.href, title:document.title||'',
                      detail:/目录导航/.test(b) && /基础信息/.test(b),
                      login:!!document.getElementById('UserName')};
            }""")
            return r if isinstance(r, dict) else {}
        except Exception:
            return {}

    def _find_detail_page(self, pages):
        """找企业详情页（正文同时含「目录导航」「基础信息」）。后开的标签页优先。"""
        for p in reversed(list(pages)):
            if self._page_flags(p).get("detail"):
                return p
        return None

    def _find_login_page(self, pages):
        """找平台弹出的登录页（shiming 子站，或页面上有 #UserName）。"""
        for p in reversed(list(pages)):
            try:
                url = p.url or ""
            except Exception:
                url = ""
            if "shiming.gsxt.gov.cn" in url or self._page_flags(p).get("login"):
                return p
        return None

    def _wait_detail(self, pages, timeout: int = 30):
        """等详情页出现。遇到 Environment Checking 只等不刷新。"""
        deadline = time.time() + timeout
        hinted = False
        page0 = pages[0] if pages else None
        while True:
            self.engine.check_stop()
            hit = self._find_detail_page(pages)
            if hit is not None:
                return hit
            if time.time() >= deadline:
                return None
            if not hinted:
                checking = any("Environment" in (self._page_flags(p).get("title") or "")
                               for p in pages)
                if checking:
                    self.engine.log("  详情页正在做环境校验（Environment Checking），等待自动放行…")
                    hinted = True
            self.engine.sleep(1.5)
            # 期间可能又开了新标签页，重新取一次
            if page0 is not None:
                try:
                    pages = list(page0.context.pages)
                except Exception:
                    pass

    def _locate_active_page(self, page):
        """在浏览器上下文里找 gsxt 的实际页面（优先 #keyword 所在的页）。"""
        try:
            pages = list(page.context.pages)
        except Exception:
            return None
        # 1) 找搜索框已就绪的页
        for p in pages:
            try:
                if p.evaluate("()=>!!document.getElementById('keyword')"):
                    return p
            except Exception:
                continue
        # 2) 找 URL 是 gsxt 的页
        for p in pages:
            try:
                if "gsxt.gov.cn" in (p.url or ""):
                    return p
            except Exception:
                continue
        return None

    def solve_captcha_if_any(self, page) -> bool:
        """页面上有图形验证码时，尝试用打码服务自动过（含刷新重试）。

        gsxt 有两套验证：
          · 极验 geetest 点选/滑块（``选 3 个符合右图的图片``）——官方题型
            不支持，只能人工；
          · 图形验证码（``#popup-captcha``）——打码服务可以自动过。

        返回 True 表示已经自动过掉（或本来就没有验证码）。
        """
        try:
            popup = page.evaluate("""()=>{
              const p=document.getElementById('popup-captcha');
              if(!p) return null;
              const b=p.getBoundingClientRect();
              return {w:b.width,h:b.height,
                      imgs:[...p.querySelectorAll('img')].map(i=>i.src).slice(0,3)};}""")
        except Exception:
            popup = None
        if not popup or popup.get("w", 0) < 40:
            return True   # 没有图形验证码弹窗
        self.engine.log("  检测到图形验证码，尝试打码服务自动识别…")
        ok = self.engine.captcha_solver.solve_image_captcha(
            page, img_selector="img", scope_selector="#popup-captcha",
            verify_texts=("验证", "确定", "确认"))
        if ok:
            # 点弹窗里的提交按钮
            page.evaluate("""()=>{const b=document.getElementById('pop-captcha-submit');
              if(b) b.click();}""")
            self.engine.sleep(2.0)
        return ok

    def collect_basic(self, page, company: str, code: str, step: dict) -> str:
        """gsxt 企业详情 - 基础信息 + 全部股东及出资详细信息。"""
        self.enter_detail(page, company)
        page = getattr(self, "_gsxt_page", None) or page
        page = self._live_page(page) or page
        click_by_text(page, "基础信息", exact=False)
        self.engine.sleep(1.5)
        expanded = page.evaluate("""
        ()=>{
          const cands=[...document.querySelectorAll('a,span,div,button')]
            .filter(e=>/全部股东|股东及出资详细信息|查看全部/.test((e.innerText||'').trim()));
          if(!cands.length) return 'NONE';
          const e=cands[0];
          e.scrollIntoView({block:'center'});
          e.click();
          return 'CLICK:'+(e.innerText||'').trim().slice(0,24);
        }""")
        self.engine.log("  展开股东详细信息：%s" % expanded)
        self.engine.sleep(2.5)
        page.evaluate("()=>{const e=[...document.querySelectorAll('a,span,div')]"
                      ".find(x=>/全部股东|股东及出资详细信息/.test((x.innerText||'').trim()));"
                      "if(e) e.scrollIntoView({block:'center'});}")
        self.engine.sleep(1.2)
        return ""

    def click_left_nav(self, page, kw: str) -> str:
        """点击详情页左侧「目录导航」里的指定条目（如「行政处罚信息」）。

        位置：左侧「目录导航」→「违法失信信息」分组下（用户截图标注）。
        优先在「目录导航」容器内找；找不到再按「位于页面左侧 30% 内」兜底；
        还没有就先展开「违法失信信息」分组再找。
        """
        try:
            return str(page.evaluate("""
            (arg)=>{
              const W=window.innerWidth;
              const norm=s=>(s||'').replace(/\\s+/g,'').trim();
              const navRoot=(()=>{
                const t=[...document.querySelectorAll('div,span,h1,h2,h3,p,a,label')]
                  .find(e=>norm(e.innerText||e.textContent||'')==='目录导航');
                if(!t) return null;
                let p=t;
                for(let i=0;i<7 && p.parentElement;i++){
                  p=p.parentElement;
                  if(p.querySelectorAll('a,li,span,div').length>=8) return p;
                }
                return t.parentElement||t;
              })();
              const collect=(root)=>[...root.querySelectorAll('a,span,div,li,em,i,label')]
                .filter(e=>{
                  const t=norm(e.innerText||e.textContent||'');
                  if(!t || t.length>30 || !t.includes(arg.kw)) return false;
                  const r=e.getBoundingClientRect();
                  return r.width>0 && r.height>0;
                });
              let cands = navRoot ? collect(navRoot) : [];
              if(!cands.length){
                cands=[...document.querySelectorAll('a,span,div,li,em,i,label')].filter(e=>{
                  const t=norm(e.innerText||e.textContent||'');
                  if(!t || t.length>30 || !t.includes(arg.kw)) return false;
                  const r=e.getBoundingClientRect();
                  return r.width>0 && r.height>0 && r.x < W*0.30;
                });
              }
              if(!cands.length){
                const grp=[...document.querySelectorAll('a,span,div,li')]
                  .filter(e=>norm(e.innerText||e.textContent||'')==='违法失信信息');
                if(grp.length){ grp[0].click(); }
                cands = navRoot ? collect(navRoot) : [];
              }
              if(!cands.length) return 'NONE';
              cands.sort((a,b)=>norm(a.innerText||a.textContent||'').length
                                -norm(b.innerText||b.textContent||'').length);
              const e=cands[0];
              e.scrollIntoView({block:'center'});
              e.click();
              return 'CLICK:'+norm(e.innerText||e.textContent||'').slice(0,24);
            }""", {"kw": kw}))
        except Exception as exc:
            return "ERR:%s" % str(exc).splitlines()[0]

    def collect_section(self, page, company: str, code: str, step: dict) -> str:
        """gsxt 企业详情页的某个板块。

        三个板块都在详情页**左侧「目录导航」→「违法失信信息」**分组下（用户截图标注）：
            行政处罚信息
            列入经营异常名录信息
            列入严重违法失信名单（黑名单）信息

        详情页是单页长滚动，所有板块依次排列，所以：
            1) 点左侧目录项 → 页面滚动定位到同名板块；
            2) 再把板块标题滚到视口顶部（避开固定的头部）；
            3) 用**可视区截图**（不是整页），这样每张图只包含对应板块。
        """
        if not getattr(self, "_gsxt_in_detail", False):
            self.enter_detail(page, company)
        page = getattr(self, "_gsxt_page", None) or page
        page = self._live_page(page) or page

        kw = (step.get("section") or "").strip()
        if not kw:
            raise EngineError("未指定 gsxt 板块名称")

        clicked = self.click_left_nav(page, kw)
        self.engine.log("  点击左侧目录「%s」：%s" % (kw, clicked))
        if not str(clicked).startswith("CLICK"):
            self.engine.log("  ⚠ 左侧目录里没找到「%s」，按当前画面截图" % kw)
        self.engine.sleep(2.5)

        # 把板块标题滚到视口顶部（避开固定头部）
        page.evaluate("""
        (arg)=>{
          const norm=s=>(s||'').replace(/\\s+/g,'');
          const hits=[...document.querySelectorAll('h1,h2,h3,h4,div,span,p,strong')]
            .filter(e=>{
              const t=norm(e.innerText||e.textContent||'');
              return t===arg.kw || (t.startsWith(arg.kw) && t.length<=arg.kw.length+10);
            });
          if(!hits.length) return 'NONE';
          // 取正文区（不在左侧导航里）的那个
          const W=window.innerWidth;
          const h=hits.find(e=>e.getBoundingClientRect().x>=W*0.15) || hits[hits.length-1];
          h.scrollIntoView({block:'start'});
          window.scrollBy(0,-120);
          return 'SCROLL';
        }""", {"kw": kw})
        self.engine.sleep(1.8)

        st = page.evaluate("""
        (arg)=>{
          const norm=s=>(s||'').replace(/\\s+/g,'');
          const body=document.body.innerText||'';
          const hit=body.includes(arg.kw);
          const no=/暂无/.test(body);
          return {hit, no, snippet:body.replace(/\\n+/g,' | ').slice(0,200)};
        }""", {"kw": kw})
        self.engine.log("  板块已定位：%s%s" % (kw, "（页面显示「暂无」相关记录）" if st.get("no") else ""))
        return ""

    def collect_blacklist(self, page, company: str, code: str, step: dict) -> str:
        """gsxt 严重违法失信企业名单（黑名单）查询。"""
        # 前一组可能清理过标签页，传入的 page 已死 → 先解析活页
        page = self._live_page(page) or page
        self.open_portal(page)
        # 上级目录跳转可能开了新标签页
        page = getattr(self, "_gsxt_page", None) or page
        page = self._live_page(page) or page
        clicked = "NONE"
        for attempt in range(1, 4):
            clicked = eval_retry(page, """
            ()=>{
              const els=[...document.querySelectorAll('a,li,span,div')]
                .filter(e=>{const t=(e.innerText||'').replace(/\\s+/g,'').trim();
                            return t==='严重违法失信名单'||t==='严重违法失信企业名单';});
              if(!els.length) return 'NONE';
              els[0].click();
              return 'CLICK';
            }""")
            self.engine.log("  进入「严重违法失信名单」：%s" % clicked)
            if str(clicked).startswith("CLICK"):
                break
            if attempt < 3:
                self.engine.log("  ↻ 导航项没找到，重新加载首页再试（第 %d 次）" % (attempt + 1))
                self.open_portal(page)
        if not str(clicked).startswith("CLICK"):
            raise EngineError("gsxt 首页未找到「严重违法失信名单」入口")
        self.engine.sleep(4)

        # 切到「严重违法失信名单」后页面会重新渲染，等搜索框重新可见再填
        self.wait_keyword(page, timeout=20)

        finders = [
            "() => document.getElementById('keyword')",
            "() => document.querySelector(\"input[name='searchword']\")",
            "() => [...document.querySelectorAll('input')]"
            ".find(x => (x.placeholder||'').includes('企业名称'))",
        ]
        filled = False
        for js in finders:
            try:
                if fill_controlled(page, js, company) or set_native(page, js, company):
                    self.engine.log("  已填入企业名称：%s" % company)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            raise EngineError("gsxt 黑名单页查询框定位失败")

        self.engine.sleep(0.6)
        click_by_text(page, "查 询", exact=False)
        if not click_by_text(page, "查询", exact=False):
            page.evaluate("()=>{const b=[...document.querySelectorAll('button,a,input')]"
                          ".find(e=>(e.innerText||e.value||'').replace(/\\s+/g,'')==='查询');"
                          "if(b) b.click();}")
        self.engine.sleep(4)

        if page.evaluate("()=>!!document.querySelector('.geetest_holder,.geetest_panel')"):
            self.engine.wait_manual("gsxt 黑名单查询触发验证码，请完成验证。")

        deadline = time.time() + self.engine.timeout
        ready = False
        while time.time() < deadline:
            self.engine.check_stop()
            st = page.evaluate("""
            ()=>{
              const b=document.body.innerText||'';
              const hit=/未列入|没有列入|无相关|未查询到|查询结果|严重违法失信名单|共\\s*\\d+\\s*条/.test(b);
              return {hit, snippet:b.replace(/\\n+/g,' | ').slice(0,260)};
            }""")
            if st and st.get("hit"):
                ready = True
                break
            self.engine.sleep(2)
        if ready:
            self.engine.log("  黑名单查询结果已刷新")
        else:
            self.engine.log("  等待结果超时，按当前画面截图")
        return ""
