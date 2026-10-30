# -*- coding: utf-8 -*-
"""platforms/cnca.py —— 全国认证认可信息公共服务平台（cx.cnca.cn）。

采集链路（用户给的业务口径）
----------------------------
1. 首页「认证结果查询」→ 填**企业名称** → 点【查询】
   → **整页跳转**到「认证结果综合查询」页（``result/skipResultList``）
   → 在结果页**再填一次企业名称** → 点【查询】
   → 弹出极验点选验证码（人工完成）
   → 列出**组织列表**（获证组织 + 统一社会信用代码）；
2. 点组织列表里的目标组织 → 再弹极验（人工完成）
   → 展开该组织的**证书列表**（证书编号 / 状态 / 到期日期）→ **截图 1**；
3. 点证书卡片（``skipDetail(n)``）→ 再弹极验（人工完成）
   → 打开证书**详细信息**页（新标签）→ **截图 2**。

站点实现要点（抓前端 JS 逆出来的，写在这里免得以后再猜）
----------------------------------------------------------
* 三处验证码都是**极验 v4**（``geetest.js`` 里 ``geetest4()``，
  ``captcha_id`` 固定 ``08c16c99330a5a1d6b7f4371bbd5a978``，``product=bind``）。
  官方打码服务**没有极验题型** → 一律转人工（与项目既有约束一致）。
* 首页按钮 ``indexQueryCert()`` **不弹验证码**，直接
  ``window.location.href = ".../result/skipResultList?certNumber=&orgName=xxx&fromIndex=true"``。
* 结果页按钮 ``queryCertInfo()`` 才弹验证码。
* **坑**：结果页服务端把隐藏域 ``#fromIndex`` 渲染成字符串 ``"false"``，
  于是 ``queryCertInfo()`` 里的 ``fromIndex == "true"`` 判断不成立，
  它不会去取 ``#orgNameIndex``，而是读**可见输入框** ``#orgName`` ——
  而那个框服务端没填值 → ``condIsNull()`` 直接 return，页面只显示
  「请输入查询条件!」。**所以必须在结果页重新填一次企业名称。**
* 前端用 4 个开关决定验证通过后走哪条分支：
  ``showCheckTwice1=查询`` / ``2=组织证书列表`` / ``3=按证书编号查`` / ``4=证书详情``。
* 每阶段验证通过后由站点自己发 AJAX：
  - 阶段1 ``GET ../result/listAuthresultByOrg`` → 渲染 ``.orgContent``（组织列表）
  - 阶段2 ``GET ../result/listAuthresultForOrg`` → 渲染 ``.certContent``（证书列表）
  - 阶段4 ``window.open('../result/skipDetail?...')`` → 新标签页打开证书详情
* 组织列表行：``class="orgInfoRow<n>"``（**类名带数字后缀**），
  行内 ``#orgName<n>`` / ``#orgId<n>``，点击行触发 ``listCertForOrg(n)``；
  所在容器 ``#orgListDiv`` 初始是 ``divHidden``，渲染后才变 ``divShow``。
* 证书卡片：``.certInfoSingle``（id ``certInfo<n>``），内含隐藏域
  ``rzjgId / certNumber / showtemp / certItemOne / etlId``，
  点击触发 ``skipDetail(n)``；所在容器 ``#certListDiv`` 默认可见。

所以这里**不去直接调接口**（接口要带极验的四个 token，手工拼容易踩坑），
而是**驱动页面上的真实按钮**，让站点自己的 JS 完成校验与渲染 ——
人工过完极验后页面自然就出内容了，截图即真实界面。
"""
from __future__ import annotations

import re
import time
from typing import List

from core.errors import Aborted, EngineError, Skipped
from core.result import StepResult
from platforms.base import PlatformHandler

__all__ = ["CncaHandler"]

HOME = "https://cx.cnca.cn/CertECloud/index/index/page"
RESULT_URL = "https://cx.cnca.cn/CertECloud/result/skipResultList"

#: 组织列表行 / 证书卡片的行号（站点 JS 用 1 起编号）
#: 组织行选择器（类名带数字后缀，必须用前缀匹配）
ORG_ROW_FMT = '[class^="orgInfoRow"]'

#: 页面初始就带着的占位提示，不算「查无记录」
PLACEHOLDER = "请输入查询条件"

#: 极验弹层是否真的显示（顶层容器有尺寸，且祖先链没有 display:none）
#:
#: 注意：实测 cn.cnca.cn 的极验 v4 **展开与收起时 DOM 完全一样** ——
#: ``.geetest_captcha`` / ``.geetest_box_wrap`` 的 offsetHeight 恒为 0
#: （极验用绝对定位 + 溢出显示），``.geetest_box`` 恒为 340x386。
#: 所以**尺寸判据无法区分弹层开合**，只能靠「站点调用了 gt.showCaptcha」
#: 这个信号（见 :data:`GEETEST_HOOK_JS`）。本判据只作辅助。
GEETEST_VISIBLE_JS = """()=>{
  const visible=(e)=>{
    if(!e) return false;
    let n=e;
    while(n && n!==document.documentElement){
      const st=getComputedStyle(n);
      if(st.display==='none'||st.visibility==='hidden') return false;
      if(n!==e && n.offsetHeight===0 && n.offsetWidth===0) return false;
      n=n.parentElement;
    }
    const r=e.getBoundingClientRect();
    return r.width>=30 && r.height>=30;
  };
  const sels=['.geetest_captcha','.geetest_box_wrap','.geetest_panel'];
  for(const s of sels){
    for(const e of document.querySelectorAll(s)) if(visible(e)) return true;
  }
  for(const f of document.querySelectorAll('iframe')){
    if(/geetest|gcaptcha/i.test(f.src||'')) if(visible(f)) return true;
  }
  return false;
}"""

#: 注入脚本：记录极验被唤起的次数。
#:
#: ``gt`` 是异步初始化的（``geetest4().then(gt => window.gt = gt)``），
#: 所以这里用定时器等它出现再包一层 ``showCaptcha``。
#: 包装只做计数，不改变行为（``o.apply(window.gt, arguments)`` 保持 this）。
GEETEST_HOOK_JS = """()=>{
  if(window.__csHooked) return 'ALREADY';
  window.__csGeetestCalls = 0;
  const iv = setInterval(()=>{
    try{
      if(window.gt && window.gt.showCaptcha && !window.gt.__csWrapped){
        const o = window.gt.showCaptcha.bind(window.gt);
        window.gt.showCaptcha = function(){
          window.__csGeetestCalls = (window.__csGeetestCalls||0) + 1;
          return o.apply(window.gt, arguments);};
        window.gt.__csWrapped = true;
      }
    }catch(e){}
  }, 100);
  setTimeout(()=>{try{clearInterval(iv);}catch(e){}}, 600000);
  window.__csHooked = true;
  return 'OK';
}"""


class CncaHandler(PlatformHandler):
    """全国认证认可信息公共服务平台的采集处理器。"""

    key = "cnca"
    title = "全国认证认可信息公共服务平台"

    def __init__(self, engine):
        super().__init__(engine)
        # 当前页面（证书详情会开新标签页）
        self._page = None
        # 证书详情新标签页
        self._detail_page = None

    # ------------------------------------------------------------ 生命周期
    def reset_subject_state(self) -> None:
        self._page = None
        self._detail_page = None

    # ------------------------------------------------------------ 主入口
    def collect_group(self, page, company: str, gsteps: List[dict],
                      results: List[StepResult], shots: List[str]) -> None:
        """CNCA 两项共用一次「进站点 + 查询」，中间靠页面状态衔接。"""
        try:
            self.search(page, company)
        except (Aborted, Skipped):
            raise
        except Exception as exc:
            self.engine.log("  ✘ 查询失败：%s" % str(exc).splitlines()[0])
            for step in gsteps:
                results.append(StepResult(step["no"], step["key"], step["title"],
                                          company, False, message=str(exc)))
            return

        page = self._page or page

        # ---- 第 1 项：证书列表 ----
        list_step = next((s for s in gsteps if s.get("sub_step") == "list"), None)
        detail_step = next((s for s in gsteps if s.get("sub_step") == "detail"), None)

        if list_step is not None:
            self._run_step(page, company, list_step, results, shots,
                           lambda p: self.reveal_cert_list(p, company))

        # ---- 第 2 项：证书详细信息（遍历截取所有有效证书的详情页）----
        if detail_step is not None:
            self._run_detail_steps(page, company, detail_step, results, shots)

    def _run_step(self, page, company: str, step: dict,
                  results: List[StepResult], shots: List[str], action) -> None:
        """跑一个采集项：执行 action（负责把页面带到目标状态）再截图。

        与 ``engine.run_one`` 语义一致：点【跳过此步】只跳当前这一项，
        后续采集项照常进行。
        """
        t0 = time.time()
        try:
            self.engine.check_stop()
            self.engine.log("[%s] %s" % (step["no"], step["title"]))
            target = action(page)
            path = self.engine.shot_step(target or page, company, step)
            shots.append(path)
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, True, path=path,
                                      elapsed=time.time() - t0))
        except Skipped:
            self.engine.log("  ⤼ 本步已跳过")
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, False, message="已跳过",
                                      elapsed=time.time() - t0))
        except Aborted:
            raise
        except Exception as exc:
            self.engine.log("  ✘ 失败：%s" % str(exc).splitlines()[0])
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, False, message=str(exc),
                                      elapsed=time.time() - t0))

    def _run_detail_steps(self, page, company: str, step: dict,
                          results: List[StepResult], shots: List[str]) -> None:
        """跑证书详细信息项：针对所有「有效」证书逐条点击进入详细页面并分别截图存证。"""
        t0 = time.time()
        try:
            self.engine.check_stop()
            self.engine.log("[%s] %s" % (step["no"], step["title"]))
            # 确保证书列表已就绪
            if not self.count_certs(page):
                self.reveal_cert_list(page, company)

            cards = self.pick_valid_cert_cards(page)
            if not cards:
                raise EngineError("证书列表里没有找到可查询的证书卡片")

            valid_cards = [c for c in cards if c.get("isValid")]
            target_cards = valid_cards if valid_cards else cards
            self.engine.log("  找到 %d 张证书（其中有效证书 %d 张），将逐一查询并截图详情页面"
                            % (len(cards), len(valid_cards)))

            main_path = ""
            detail_paths = []
            for idx, c in enumerate(target_cards, start=1):
                self.engine.check_stop()
                card_num = c["index"]
                desc = c.get("certNumber") or ("证书%d" % card_num)
                status_text = "有效" if c.get("isValid") else (c.get("status") or "未知状态")
                self.engine.log("  → 正在查询第 %d/%d 张证书详情（[%s] %s）…"
                                % (idx, len(target_cards), status_text, desc))

                # 点击卡片
                clicked = page.evaluate("""(n)=>{
                  const card = document.getElementById('certInfo' + n);
                  if(!card) return 'NO_CARD';
                  card.scrollIntoView({block: 'center'});
                  card.click();
                  return 'CLICK';
                }""", card_num)
                if clicked != "CLICK":
                    self.engine.log("  ⚠ 证书卡片 certInfo%d 点击失败，跳过该张" % card_num)
                    continue

                self.engine.sleep(1.0)
                # 等待极验验证（若触发）
                self.wait_geetest(page, "证书详细信息（第%d张）" % idx)

                # 等新标签页打开
                detail_p = self.wait_detail_page(page)
                if detail_p is None:
                    self.engine.log("  ⚠ 未能打开第 %d 张证书详情标签页" % idx)
                    continue

                sub_step = dict(step)
                if idx > 1:
                    sub_step["title"] = "%s - 证书%d(%s)" % (step["title"], idx, desc)
                shot_path = self.engine.shot_step(detail_p, company, sub_step)
                shots.append(shot_path)
                detail_paths.append(shot_path)
                if not main_path:
                    main_path = shot_path

                # 截完关闭详情标签页，切回主列表继续下一张
                try:
                    detail_p.close()
                except Exception:
                    pass
                self.engine.sleep(1.0)

            if not main_path:
                raise EngineError("所有有效证书详情页均未能成功打开")

            msg = "共完成 %d 张有效证书详情截图" % len(detail_paths)
            self.engine.log("  ✔ %s" % msg)
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, True, path=main_path,
                                      elapsed=time.time() - t0, message=msg))
        except Skipped:
            self.engine.log("  ⤼ 本步已跳过")
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, False, message="已跳过",
                                      elapsed=time.time() - t0))
        except Aborted:
            raise
        except Exception as exc:
            self.engine.log("  ✘ 失败：%s" % str(exc).splitlines()[0])
            results.append(StepResult(step["no"], step["key"], step["title"],
                                      company, False, message=str(exc),
                                      elapsed=time.time() - t0))

    # ------------------------------------------------------------ 第 1 步：查询
    def search(self, page, company: str):
        """首页填企业名称 → 点查询跳到结果页 → 结果页再填一次 → 过极验 → 组织列表。"""
        from core import nav

        self.engine.log("打开全国认证认可信息公共服务平台：%s" % HOME)
        # 走统一导航层（该站有 WAF，直连易被判异常 IP）
        res = nav.goto_via_landing(page, "cnca", log=self.engine.log,
                                   timeout_ms=self.engine.timeout * 1000)
        if res.get("page") is not None:
            page = res["page"]
        if not res.get("ok"):
            self.engine.log("  ⚠ 上级目录跳转未成功，直接打开目标页")
            nav.goto(page, HOME, timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log, referer=nav.site_referer("cnca"))
        self._page = page

        # ---- 首页：填企业名称 → 点【查询】→ 整页跳转 ----
        # 用 pathname 判断是不是首页：结果页也有 #orgName 输入框，光看元素会认错。
        # 实测：认监委首次落地有时需**刷新一次**才真正进入（WAF/网关二次放行），
        # 所以判定失败时先自动刷新再等一轮，而不是直接报错。
        ok = self.wait_ready(
            page,
            "()=>location.pathname.indexOf('/index/index/page')>=0"
            " && !!document.getElementById('orgName')",
            timeout=40)
        if not ok:
            self.engine.log("  ↻ 首页未就绪，自动刷新一次再等（站点常需二次放行）")
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            ok = self.wait_ready(
                page,
                "()=>location.pathname.indexOf('/index/index/page')>=0"
                " && !!document.getElementById('orgName')",
                timeout=40)
        if not ok:
            raise EngineError("CNCA 首页没就绪（找不到企业名称输入框）")
        self.engine.sleep(1.5)

        self.fill_org_name(page, company)
        self.engine.sleep(0.6)

        clicked = page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(!b) return 'NONE';
          b.click();
          return 'CLICK';
        }""")
        if clicked != "CLICK":
            raise EngineError("没找到【查询】按钮")
        self.engine.log("  已填入企业名称并点【查询】，等待跳转到综合查询页…")

        # 首页是整页跳转，等新地址生效
        try:
            page.wait_for_url(re.compile(r"skipResultList"), timeout=30000)
        except Exception:
            self.engine.log("  ⚠ 没等到页面跳转，直接打开综合查询页")
            nav.goto(page, RESULT_URL, timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log, referer=nav.site_referer("cnca"))
        self.engine.sleep(2.0)

        # ---- 结果页：必须**再填一次**企业名称（服务端没给可见输入框填值）----
        ok = self.wait_ready(
            page, "()=>!!document.getElementById('orgName')", timeout=30)
        if not ok:
            raise EngineError("综合查询页没就绪")
        self.engine.sleep(1.0)
        # 注入极验计数钩子：弹层展开/收起在 DOM 上分不出来（见 GEETEST_HOOK_JS）
        self.inject_geetest_hook(page)
        self.fill_org_name(page, company)
        self.engine.sleep(0.6)

        clicked = page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button')];
          const b=bs.find(x=>/queryCertInfo/.test(x.getAttribute('onclick')||''));
          if(!b) return 'NONE';
          b.click();
          return 'CLICK';
        }""")
        if clicked != "CLICK":
            raise EngineError("综合查询页没找到【查询】按钮")
        self.engine.log("  已在综合查询页重新填入企业名称，点【查询】，等待极验验证…")

        # ---- 极验点选（人工）----
        self.wait_geetest(page, "查询（第一段验证）")
        self.engine.sleep(2.0)

        # ---- 等组织列表渲染出来 ----
        got = self.wait_ready(
            page,
            "()=>document.querySelectorAll('.orgContent tr[class^=\"orgInfoRow\"]').length>0",
            timeout=45)
        if not got:
            # 可能是「查无记录」：把结果页作为无记录存证
            state = self.read_state(page)
            if state.get("empty"):
                raise EngineError("该企业在认证认可平台无认证记录")
            raise EngineError("过完验证后没等到组织列表")
        rows = self.count_org_rows(page)
        self.engine.log("  ✔ 已进入「认证结果综合查询」，组织列表 %d 行" % rows)
        return page

    def fill_org_name(self, page, company: str) -> None:
        """把企业名称填进可见的「获证组织名称」输入框。

        Vue/普通 jQuery 页面都要求用原生 setter + input/change 事件赋值，
        否则站点自己的 ``$("#orgName").val()`` 读不到。
        """
        filled = page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(!e) return 'NO_INPUT';
          e.focus();
          const proto=HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(e,name);
          e.dispatchEvent(new Event('input',{bubbles:true}));
          e.dispatchEvent(new Event('change',{bubbles:true}));
          return e.value===name ? 'OK' : 'BAD';
        }""", company)
        if filled != "OK":
            raise EngineError("企业名称输入框定位失败（%s）" % filled)

    # ------------------------------------------------------------ 第 2 步：证书列表
    def reveal_cert_list(self, page, company: str):
        """点组织列表里的目标组织 → 过极验 → 展开证书列表。"""
        idx = self.pick_org_row(page, company)
        if idx is None:
            raise EngineError("组织列表里没有匹配的企业")
        self.engine.log("  点击组织列表第 %d 行" % idx)

        clicked = page.evaluate("""(n)=>{
          const rows=[...document.querySelectorAll('[class^="orgInfoRow"]')];
          const row=rows.find(tr=>{
            const m=(tr.className||'').match(/orgInfoRow(\\d+)/);
            return m && Number(m[1])===n;});
          if(!row) return 'NO_ROW';
          row.click();
          return 'CLICK';
        }""", idx)
        if clicked != "CLICK":
            raise EngineError("组织列表行点击失败")
        self.engine.sleep(1.2)

        self.wait_geetest(page, "组织证书列表（第二段验证）")
        self.engine.sleep(2.0)

        got = self.wait_ready(
            page,
            "()=>document.querySelectorAll('.certContent .certInfoSingle').length>0",
            timeout=45)
        if not got:
            state = self.read_state(page)
            if state.get("empty"):
                raise EngineError("该组织没有认证证书记录")
            raise EngineError("过完验证后没等到证书列表")
        n = self.count_certs(page)
        self.engine.log("  ✔ 证书列表已展开，共 %d 张证书" % n)
        return page

    # ------------------------------------------------------------ 第 3 步：证书详情
    def open_cert_detail(self, page, company: str):
        """点证书卡片 → 过极验 → 打开证书详细信息页。"""
        # 证书列表可能还没展开（上一项失败/被跳过），这里补一次
        if not self.count_certs(page):
            self.reveal_cert_list(page, company)

        idx = self.pick_cert_card(page)
        if idx is None:
            raise EngineError("证书列表里没有可展开的证书")
        self.engine.log("  点击第 %d 张证书查看详细信息" % idx)

        clicked = page.evaluate("""(n)=>{
          const c=document.getElementById('certInfo'+n);
          if(!c) return 'NO_CARD';
          c.click();
          return 'CLICK';
        }""", idx)
        if clicked != "CLICK":
            raise EngineError("证书卡片点击失败")
        self.engine.sleep(1.2)

        self.wait_geetest(page, "证书详细信息（第三段验证）")

        # 站点用 window.open 打开详情页 → 等新标签页
        detail = self.wait_detail_page(page)
        if detail is None:
            raise EngineError("过完验证后没打开证书详情页")
        self._detail_page = detail
        self.engine.log("  ✔ 已打开证书详细信息页")
        return detail

    # ------------------------------------------------------------ 极验等待
    def inject_geetest_hook(self, page) -> None:
        """在结果页注入极验计数钩子（幂等）。

        必须**在页面跳转到结果页之后**注入 —— 跳转会产生新文档，钩子会丢。
        """
        try:
            page.evaluate(GEETEST_HOOK_JS)
        except Exception:
            pass

    def geetest_asked(self, page) -> int:
        """站点一共唤起过几次极验（0 = 还没弹）。"""
        try:
            r = page.evaluate("()=>window.__csGeetestCalls||0")
        except Exception:
            return 0
        try:
            return int(r or 0)
        except Exception:
            return 0

    def wait_geetest(self, page, what: str, timeout: int = 300) -> None:
        """等极验被唤起 → 交人工 → 交回。

        极验 v4 的绑定模式（product=bind）要求验证在**同一个浏览器会话**里完成，
        打码服务没有对应题型，所以这一段只能人工。

        判据说明：极验弹层展开与收起时 DOM 尺寸完全一样（见
        :data:`GEETEST_VISIBLE_JS` 的注释），所以这里用
        「站点调用了 gt.showCaptcha」作为「弹层已唤起」的唯一可靠信号。
        验证是否通过，由调用方等页面内容渲染出来判定。
        """
        # 1) 等极验被唤起（站点判定无需验证时会直接出内容）
        deadline = time.time() + 30
        asked = 0
        while time.time() < deadline:
            self.engine.check_stop()
            asked = self.geetest_asked(page)
            if asked:
                break
            # 内容已经渲染出来 → 说明站点没要验证
            if self.geetest_done(page):
                self.engine.log("  ⓘ 本次无需极验验证（内容已直接渲染）")
                return
            self.engine.sleep(0.5)
        if not asked:
            self.engine.log("  ⓘ 未检测到极验弹层，继续流程")
            return

        self.engine.log("  ⏸ 极验点选验证码已弹出（%s）" % what)
        self.engine.wait_manual(
            "请在浏览器里完成极验「请在下图依次点击」验证（%s），"
            "完成后点【我已处理，继续截图】。" % what)
        # 验证通过后由站点自己的 JS 发 AJAX 渲染内容，
        # 这里不做「弹层消失」判断（DOM 上分不出来），交给调用方等内容。

    def geetest_visible(self, page) -> bool:
        """极验弹层是否真的显示。

        注意：极验 v4 的 DOM 里 ``.geetest_box`` 一直存在且带固定高度
        （未展开时是 386px），只看它会**永远误判为弹层已出现**。
        必须看顶层容器（``.geetest_captcha`` / ``.geetest_box_wrap``）的尺寸。
        """
        try:
            r = page.evaluate(GEETEST_VISIBLE_JS)
        except Exception:
            return False
        return bool(r)

    def wait_detail_page(self, page, timeout: int = 45):
        """等站点用 window.open 开出来的证书详情标签页。"""
        try:
            before = {id(p) for p in list(page.context.pages)}
        except Exception:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                pages = list(page.context.pages)
                # 站点开的是 ../result/skipDetail?…（RoHS 证书是 skipRoHSDetail）
                for p in pages:
                    u = p.url or ""
                    if "skipDetail" in u or "skipRoHSDetail" in u:
                        try:
                            p.wait_for_load_state("domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                        self.engine.sleep(2.0)
                        return p
                # 退一步：只要多了一个新标签页且有内容，也算
                for p in pages:
                    if id(p) not in before and (p.url or "").startswith("http"):
                        try:
                            p.wait_for_load_state("domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                        self.engine.sleep(2.0)
                        return p
            except Exception:
                pass
            self.engine.sleep(0.8)
        return None

    # ------------------------------------------------------------ 页面信息
    def read_state(self, page) -> dict:
        """读页面上的提示信息，判断是不是「查无记录」。

        占位提示（``请输入查询条件!``）是页面自带的，查询成功后仍留在
        ``.orgWarn`` 里（只是被 hide），所以**不能**拿它当「无记录」。
        只有换成别的文案（站点的 info.msg）才算真的查无记录。
        """
        try:
            r = page.evaluate("""(ph)=>{
              const orgs=document.querySelectorAll('.orgContent tr[class^="orgInfoRow"]').length;
              const certs=document.querySelectorAll('.certContent .certInfoSingle').length;
              const txt=(sel)=>{
                const e=document.querySelector(sel);
                return e?((e.innerText||e.textContent||'').trim()):'';};
              const orgWarn=txt('.orgWarn');
              const certWarn=txt('.certWarn');
              const alert=txt('#alertModal .alertContent');
              // 占位提示不算「查无记录」；换成别的文案才是真结果
              const real=(s)=>!!s && s.indexOf(ph)<0;
              return {orgs:orgs, certs:certs,
                      orgWarn:orgWarn.slice(0,160), certWarn:certWarn.slice(0,160),
                      alert:alert.slice(0,160),
                      empty: real(orgWarn)||real(certWarn)||!!alert,
                      url:location.href};
            }""", PLACEHOLDER)
        except Exception:
            return {}
        return r if isinstance(r, dict) else {}

    def count_org_rows(self, page) -> int:
        try:
            # 注意：站点的类名是 **orgInfoRow + 数字**（如 orgInfoRow1），
            # 不是 orgInfoRow —— 用 .orgInfoRow 选择器一个都选不到。
            r = page.evaluate(
                "()=>document.querySelectorAll("
                "'.orgContent tr[class^=\"orgInfoRow\"]').length")
        except Exception:
            return 0
        return int(r or 0)

    def count_certs(self, page) -> int:
        try:
            r = page.evaluate(
                "()=>document.querySelectorAll('.certContent .certInfoSingle').length")
        except Exception:
            return 0
        return int(r or 0)

    def pick_org_row(self, page, company: str):
        """在组织列表里找与查询主体最接近的一行（同名优先，否则第一行）。"""
        try:
            r = page.evaluate("""(name)=>{
              const rows=[...document.querySelectorAll(
                '.orgContent tr[class^="orgInfoRow"]')];
              if(!rows.length) return 0;
              const norm=(s)=>(s||'').replace(/\\s+/g,'')
                .replace(/[（）]/g,m=>m==='（'?'(':')');
              const want=norm(name);
              const names=rows.map(tr=>{
                const td=tr.querySelector('td[id^=orgName]');
                return td?(td.innerText||td.textContent||'').trim():'';});
              const idxOf=(pred)=>{
                for(let i=0;i<names.length;i++){
                  if(pred(norm(names[i]))) return i+1;
                }
                return 0;};
              let hit=idxOf(n=>n===want);
              if(!hit) hit=idxOf(n=>n&&want&&(n.indexOf(want)>=0||want.indexOf(n)>=0));
              if(!hit) hit=1;
              const tr=rows[hit-1];
              const m=(tr.className||'').match(/orgInfoRow(\\d+)/);
              return Number((m&&m[1])||hit);
            }""", company)
        except Exception:
            return None
        try:
            n = int(r or 0)
        except Exception:
            return None
        return n or None

    def pick_valid_cert_cards(self, page) -> List[dict]:
        """获取证书列表中所有卡片的信息并判定其是否属于「有效」证书。"""
        try:
            items = page.evaluate("""()=>{
              const cards = [...document.querySelectorAll('.certContent .certInfoSingle')];
              return cards.map(c => {
                const m = (c.id || '').match(/certInfo(\\d+)/);
                const num = m ? Number(m[1]) : 0;
                const txt = (c.innerText || '').replace(/\\s+/g, ' ');
                // 提取证书编号
                let certNumber = '';
                const mNum = txt.match(/证书编号\\s*[:：]\\s*([A-Za-z0-9_-]+)/);
                if(mNum) certNumber = mNum[1];
                // 判定是否属于有效证书
                const isProofInvalid = !!c.querySelector('.gzsbjyzmzy');
                const hasValidWord = /有效/.test(txt);
                const hasInvalidWord = /无效|撤销|暂停|注销|过期|失效/.test(txt);
                const isValid = hasValidWord && !hasInvalidWord && !isProofInvalid;
                return {
                  index: num,
                  id: c.id || '',
                  certNumber: certNumber,
                  isValid: isValid,
                  status: isValid ? '有效' : (hasInvalidWord ? '已失效/撤销' : '其他'),
                  text: txt.slice(0, 100)
                };
              }).filter(x => x.index > 0);
            }""")
            return items if isinstance(items, list) else []
        except Exception:
            return []

    def pick_cert_card(self, page):
        """取第一张有效证书卡片（若无有效则取第一张）。"""
        cards = self.pick_valid_cert_cards(page)
        if not cards:
            return None
        valid = [c for c in cards if c.get("isValid")]
        target = valid[0] if valid else cards[0]
        return target.get("index")
