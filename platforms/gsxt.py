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
        # 注意：若当前页面停在登录子站（shiming.gsxt.gov.cn）或空白页，
        # 先锚回首页域再走入口链，否则链上的 samr 落地判断会被旧页干扰。
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if "shiming.gsxt.gov.cn" in cur_url:
            self.engine.log("  当前在登录子站，先回 gsxt 首页域")
            try:
                nav.goto(page, HOME_URLS["gsxt"],
                         timeout_ms=self.engine.timeout * 1000,
                         log=self.engine.log)
                self.engine.sleep(2.0)
            except Exception:
                pass
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
                self.engine.log("  gsxt 首页未就绪，重新通过上级目录跳转进入（第 %d 次）" % (rnd + 1))
                try:
                    c2 = nav.goto_via_landing(page, "gsxt", log=self.engine.log,
                                              timeout_ms=self.engine.timeout * 1000)
                    if c2.get("page") is not None:
                        self._gsxt_page = c2["page"]
                        page = self._gsxt_page
                except Exception as exc:
                    self.engine.log("  gsxt 重新跳转异常(第%d次)：%s"
                             % (rnd, str(exc).splitlines()[0][:60]))
                self.engine.sleep(3.0)
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
        """gsxt：先免登录搜索企业 → 人工过极验并点选企业 → 切到详情新标签页。

        实测流程（2026-10-29）：
          index 页 #keyword 填名称 → #btn_query → 弹极验 → 列表页
          → 点企业**开新标签页**，先是「Environment Checking」白页，
            约 3 秒后自动变成详情页（含「目录导航」「基础信息」）。
          全程不需要登录。所以**不主动登录**；只有平台自己跳出登录页时才登录，
          登录完成后重新搜索一次。

        Environment Checking 是瑞数挑战页，**只能等，不能刷新**
        （刷新会重新挑战，用户实测「刷新等 5 秒也还是白页」）。
        """
        if getattr(self, "_gsxt_in_detail", False):
            return True
        self.open_portal(page)
        page = getattr(self, "_gsxt_page", None) or page
        self._search_company(page, company)

        for round_no in range(1, 4):
            self.engine.wait_manual(
                "gsxt 已搜索「%s」：请完成验证码/滑块，并在企业列表中点击该企业进入详情页"
                "（新标签页先显示 Environment Checking，等几秒会自动放行，不要刷新）。"
                "进入详情页后点【继续】。" % company)
            try:
                pages = list(page.context.pages)
            except Exception:
                pages = [page]

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

            detail = self._wait_detail(pages, timeout=30)
            if detail is not None:
                self._gsxt_page = detail
                self._gsxt_in_detail = True
                try:
                    detail.bring_to_front()
                except Exception:
                    pass
                self.engine.log("  ✔ 已进入企业详情页：%s" % (detail.url or "")[:90])
                return True
            self.engine.log("  ⚠ 还没找到企业详情页（第 %d 次），请确认已点击目标企业" % round_no)
        self.engine.log("  ⚠ 未能进入企业详情页，按当前页面截图")
        return False

    def _search_company(self, page, company: str) -> None:
        """在 gsxt 首页搜索框填企业名称并点【查询】（不登录）。"""
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
        # 精确触发查询按钮：gsxt 首页的搜索按钮是 <button id="btn_query" class="abs search_btn"></button>，
        # 其 innerText 是空的！不能仅按文本匹配，必须优先精确点击 #btn_query 与 .search_btn。
        clicked = page.evaluate("""()=>{
          // 先关闭可能残留的弹窗/模态层
          const closeBtns = [...document.querySelectorAll('.layui-layer-close, .popup-close, .close, [class*=close]')];
          for(const c of closeBtns){
            if(c.offsetWidth > 0 && c.offsetHeight > 0) c.click();
          }
          const btn = document.getElementById('btn_query') 
                   || document.querySelector('.search_btn')
                   || [...document.querySelectorAll('button, a, input[type=button], input[type=submit]')]
                      .find(e => /查询|搜索/.test((e.innerText||e.value||e.title||'').trim()));
          if(!btn) return 'NO_BTN';
          btn.focus();
          btn.click();
          return 'OK:' + (btn.id || btn.className || btn.tagName);
        }""")
        self.engine.log("  触发 gsxt 查询按钮：%s" % clicked)
        if not str(clicked).startswith("OK"):
            click_by_text(page, "查 询", exact=False)
            click_by_text(page, "查询", exact=False)
        self.engine.sleep(3)

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
