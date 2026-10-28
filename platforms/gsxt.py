# -*- coding: utf-8 -*-
"""国家企业信用信息公示系统 —— 国家企业信用信息公示系统：基础信息（含股东出资）、行政处罚、经营异常、严重违法失信（黑名单）等板块。

本模块只包含「这个站点怎么查」的知识；
浏览器、页面动作、截图这些通用能力在 core 包里。
所有方法体都是原 engine.py 逐字搬迁，只改了 self 引用的归属。
"""
from __future__ import annotations

import time

from core.errors import EngineError
from core.page import (click_by_text, eval_retry, fill_controlled,
                     set_native, wait_text)
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
        # 上级目录跳转可能开了新标签页，后续截图要用那个页面
        page = getattr(self, "_gsxt_page", None) or page

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
        for rnd in range(1, rounds + 1):
            ok = self.wait_keyword(page, timeout=18)
            if ok:
                if rnd > 1 or chain_res.get("via"):
                    self.engine.log("  gsxt 首页就绪（第 %d 次尝试）" % rnd)
                return True
            if rnd < rounds:
                self.engine.log("  gsxt 首页未就绪，重新加载（第 %d 次）" % (rnd + 1))
                try:
                    nav.goto(page, HOME_URLS["gsxt"],
                             timeout_ms=self.engine.timeout * 1000,
                             log=self.engine.log)
                except Exception as exc:
                    self.engine.log("  gsxt 首页打开异常(第%d次)：%s"
                             % (rnd, str(exc).splitlines()[0][:60]))
                self.engine.sleep(4.0)
        # 最后再试一次入口链（第一次可能是瑞数挑战没过）
        if not chain_res.get("ok"):
            self.engine.log("  提示：gsxt 环境校验较慢，继续尝试")
        return False

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

    def enter_detail(self, page, company: str) -> bool:
        """gsxt 首页搜索 → 人工过滑块并选中企业 → 进入企业详情页。

        滑块与「在列表里选中目标企业」这一步必须人工完成（工具挂起等待）。
        返回是否已成功进入详情页（详情页左侧有「目录导航」，标题区有「基础信息」）。
        """
        if getattr(self, "_gsxt_in_detail", False):
            return True
        self.open_portal(page)
        # 上级目录跳转可能开了新标签页，后续操作要切到那个页面
        page = getattr(self, "_gsxt_page", None) or page
        # 配了账号密码就先自动登录（登录框在主页面里）
        self.try_auto_login(page)
        self.engine.log("在 gsxt 首页搜索：%s" % company)
        # 首页可能还在载入态，填入失败就重新加载再试
        filled = False
        for attempt in range(1, 4):
            if fill_controlled(page, "() => document.getElementById('keyword')", company):
                filled = True
                break
            if set_native(page, "() => document.getElementById('keyword')", company):
                filled = True
                break
            if attempt < 3:
                self.engine.log("  ↻ 搜索框还没就绪，重新加载首页再试（第 %d 次）" % (attempt + 1))
                self.open_portal(page)
        if not filled:
            raise EngineError("gsxt 搜索框定位/填入失败")
        self.engine.sleep(0.8)
        click_by_text(page, "查 询", exact=False)
        if not click_by_text(page, "查询", exact=False):
            page.evaluate("()=>{const b=[...document.querySelectorAll('button,a,input')]"
                          ".find(e=>(e.innerText||e.value||'').replace(/\\s+/g,'')==='查询');"
                          "if(b) b.click();}")
        self.engine.sleep(4)

        self.engine.wait_manual(
            "gsxt 搜索已触发，请完成滑块/验证码，并在弹出的企业列表中选择「%s」进入企业详情页。" % company)

        detail = page.evaluate("""
        ()=>{
          const b=document.body.innerText||'';
          return {url:location.href, hasBasic:/基础信息/.test(b), nav:/目录导航/.test(b)};
        }""")
        ok = bool(detail.get("hasBasic") and detail.get("nav"))
        self._gsxt_in_detail = ok
        self.engine.log("  当前页 url=%s 基础信息=%s 目录导航=%s"
                 % (str(detail.get("url", ""))[:90], detail.get("hasBasic"), detail.get("nav")))
        if not ok:
            self.engine.log("  ⚠ 看起来还没进入企业详情页")
        return ok

    def try_auto_login(self, page) -> bool:
        """配了账号密码就自动登录 gsxt。

        公开查询其实免登录，但**登录后额度更高、验证码触发更少**，
        所以配了账号密码就自动登录一次。
        登录框在主页面里（不是 iframe），提交后可能弹极验滑块/点选 ——
        那种只能人工，程序会挂起等用户处理。
        """
        cred = self.engine.credentials.get("gsxt") or {}
        username = (cred.get("username") or "").strip()
        password = cred.get("password") or ""
        if not username or not password:
            return False
        if getattr(self, "_gsxt_logged_in", False):
            return True
        ok = self.engine.auto_login(page, "gsxt", "国家企业信用信息公示系统")
        if ok:
            self._gsxt_logged_in = True
            # 登录成功会刷新页面，重新等搜索框
            self.wait_keyword(page, timeout=20)
        return ok

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
        self.open_portal(page)
        # 上级目录跳转可能开了新标签页
        page = getattr(self, "_gsxt_page", None) or page
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
