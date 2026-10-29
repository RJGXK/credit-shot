# -*- coding: utf-8 -*-
"""信用中国 —— 信用中国（信息公示 + 专项查询）：严重失信主体名单、经营异常名录、安全生产严重失信（法人/自然人）、重大税收违法等。

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


# ---- 本平台的选择器/状态判定脚本 ----

CC_STATE_JS = """
(()=>{
  const body=document.body.innerText||'';
  let rows=0, firstRow='';
  document.querySelectorAll('table tr').forEach(tr=>{
    const t=(tr.innerText||'').replace(/\\s+/g,' ').trim();
    if(t.length>6){rows++; if(!firstRow) firstRow=t.slice(0,140);}
  });
  const nd=document.querySelector('.no-data');
  const noData=!!(nd && getComputedStyle(nd).display!=='none' && (nd.innerText||'').trim());
  const empty=/很抱歉，没有找到您搜索的数据|没有查询到相关记录|未检索到|暂无相关数据|无相关数据/.test(body);
  const pop=document.querySelector('.vcodepop');
  const popShown=!!(pop && getComputedStyle(pop).display!=='none');
  const img=document.querySelector('#vcodeimg');
  const imgOk=!!(img && img.naturalWidth>0);
  const ck=(document.cookie.match(/(?:^|;\\s*)vcode=([^;]*)/)||[])[1]||'';
  const btn=!!document.querySelector('.infoCheckBtn');
  const inp=[...document.querySelectorAll('input')].some(x=>(x.placeholder||'').includes('请输入主体名称')&&x.id!=='search_input');
  return {rows:rows, firstRow:firstRow, noData:noData, empty:empty,
          popShown:popShown, imgOk:imgOk, vcode:ck, btn:btn, inp:inp,
          snippet:body.replace(/\\n+/g,' | ').slice(0,260)};
})()
"""


class CreditChinaHandler(PlatformHandler):
    """信用中国 的采集处理器。"""

    def open_page(self, page, url: str) -> None:
        """从上级目录跳转进入目标页面。

        直连信用中国会被 WAF 拦（返回 412 空页），
        所以先落到上级门户再点进站内页面。
        """
        self.engine.log("打开：%s" % url)
        res = nav.goto_via_landing(page, "creditchina", log=self.engine.log,
                                  timeout_ms=self.engine.timeout * 1000)
        if not res.get("ok"):
            self.engine.log("  ⚠ 上级目录跳转未成功，直接打开目标页")
        try:
            nav.goto(page, url, timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log)
        except Exception as exc:
            self.engine.log("  ⚠ 打开目标页异常：%s" % str(exc).splitlines()[0][:80])

    def collect_list(self, page, company: str, code: str, step: dict) -> str:
        """信用中国名单查询（流程已实测打通）。"""
        url = step.get("url") or ""
        self.open_page(page, url)
        self.wait_ready(page, "()=>{const b=document.querySelector('.infoCheckBtn');"
                               "const e=[...document.querySelectorAll('input')]"
                               ".find(x=>(x.placeholder||'').includes('请输入主体名称')&&x.id!=='search_input');"
                               "return !!(b&&e);}", timeout=30)
        self.engine.sleep(1.0)

        finder = ("() => [...document.querySelectorAll('input')]"
                  ".find(x => (x.placeholder||'').includes('请输入主体名称') && x.id !== 'search_input')")
        ok = fill_controlled(page, finder, company)
        if not ok:
            ok = set_native(page, finder, company)
        if not ok:
            raise EngineError("信用中国输入框定位/填入失败")
        self.engine.log("已填入企业名称：%s" % company)

        # 查询按钮页面上有遮罩层，必须走 JS click
        page.evaluate("()=>{const b=document.querySelector('.infoCheckBtn'); if(b) b.click();}")
        self.engine.sleep(2.5)

        # 站点确实弹验证码时才提示人工处理（不弹就不提示）
        need_vcode = False
        deadline = time.time() + 12
        while time.time() < deadline:
            st = self.read_state(page)
            if st.get("popShown"):
                need_vcode = True
                break
            if st.get("rows") or st.get("noData"):
                break
            self.engine.sleep(1.0)

        if need_vcode:
            # 自动过验证码（带：只换验证码图 + 最内层按钮提交 + 判错重试）：
            # 信用中国特点：弹层是 .vcodepop，确认按钮是 .confirm / a.confirm，
            # 成功判据是 cookie vcode=1 或弹层消失。
            def vcode_ok() -> bool:
                s = self.read_state(page)
                return s.get("vcode") == "1" or not s.get("popShown")

            ok = self.engine.captcha_solver.solve_image_captcha(
                page,
                img_selector="#vcodeimg",
                scope_selector=".vcodepop",
                confirm_selectors=(".vcodepop a.confirm", ".vcodepop .confirm"),
                success_check=vcode_ok,
                # 信用中国的验证码 95x25、字符带描边阴影，单次识别率不高；
                # 站点判错后会自己换图，所以多试几轮更划算（实测 3 轮不够）。
                tries=5,
            )
            if not ok:
                self.engine.wait_manual("信用中国验证码未能自动识别通过，请在浏览器里输入并点【验证】。")
            self.engine.sleep(2)
            # 等验证码 cookie 生效（站点通过后才真正执行查询）
            deadline = time.time() + 60
            while time.time() < deadline:
                st = self.read_state(page)
                if st.get("vcode") == "1" or not st.get("popShown"):
                    break
                self.engine.sleep(1.0)

        # 等结果刷新
        deadline = time.time() + self.engine.timeout
        ready = False
        while time.time() < deadline:
            self.engine.check_stop()
            st = self.read_state(page)
            if not st.get("popShown"):
                if need_vcode and st.get("vcode") != "1":
                    self.engine.sleep(1.5)
                    continue
                if st.get("rows") or st.get("noData") or st.get("empty"):
                    ready = True
                    break
            self.engine.sleep(1.5)
        if ready:
            self.engine.log("  查询结果已刷新")
        else:
            self.engine.log("  等待结果超时，按当前画面截图")
        return ""

    def collect_person_list(self, page, company: str, code: str, step: dict) -> str:
        """信用中国「安全生产严重失信主体名单（自然人）」。

        实测该页表单与法人页不同，只有两个框：
            #name  请输入人员姓名
            #code  请输入身份证号后4位
        查询按钮是 .doctor-form 里的「查 询」，验证码机制与法人页一致（.vcodepop）。
        """
        url = step.get("url") or ""
        self.open_page(page, url)
        self.wait_ready(page, "()=>!!(document.getElementById('name') && document.getElementById('code'))",
                         timeout=30)
        self.engine.sleep(1.2)

        person = self.subject
        person_name = person.person.strip() if person else ""
        id_tail = person.idcard.strip()[-4:] if person else ""
        if not person_name:
            raise EngineError("该采集项需要人员姓名，请在「人员」模式下填写「人员姓名|身份证号」")

        ok_name = fill_controlled(page, "()=>document.getElementById('name')", person_name)
        if not ok_name:
            raise EngineError("自然人查询：人员姓名输入框定位/填入失败")
        ok_code = True
        if id_tail:
            ok_code = fill_controlled(page, "()=>document.getElementById('code')", id_tail)
            if not ok_code:
                self.engine.log("  提示：身份证号后 4 位填入失败，仅按姓名查询")
        self.engine.log("已填入人员姓名：%s%s" % (person_name, ("（身份证后4位 %s）" % id_tail) if id_tail else ""))

        # 提交：自然人页的查询按钮是 .doctor-form 里的「查 询」
        page.evaluate("""
        ()=>{
          const b=document.querySelector('.infoCheckBtn');
          if(b){ b.click(); return; }
          const f=document.querySelector('.doctor-form');
          const btn=f?[...f.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询'):null;
          if(btn){ btn.click(); return; }
          const alt=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(alt) alt.click();
        }""")
        self.engine.sleep(2.5)

        need_vcode = False
        deadline = time.time() + 12
        while time.time() < deadline:
            st = self.read_state(page)
            if st.get("popShown"):
                need_vcode = True
                break
            if st.get("rows") or st.get("noData"):
                break
            self.engine.sleep(1.0)

        if need_vcode:
            def vcode_ok_person() -> bool:
                s = self.read_state(page)
                return s.get("vcode") == "1" or not s.get("popShown")

            ok = self.engine.captcha_solver.solve_image_captcha(
                page,
                img_selector="#vcodeimg",
                scope_selector=".vcodepop",
                confirm_selectors=(".vcodepop a.confirm", ".vcodepop .confirm"),
                success_check=vcode_ok_person,
                tries=5,
            )
            if not ok:
                self.engine.wait_manual("信用中国（自然人名单）验证码未能自动识别通过，请在浏览器里输入并点【验证】。")
            self.engine.sleep(2)
            deadline = time.time() + 60
            while time.time() < deadline:
                st = self.read_state(page)
                if st.get("vcode") == "1" or not st.get("popShown"):
                    break
                self.engine.sleep(1.0)

        deadline = time.time() + self.engine.timeout
        ready = False
        while time.time() < deadline:
            self.engine.check_stop()
            st = self.read_state(page)
            if not st.get("popShown"):
                if need_vcode and st.get("vcode") != "1":
                    self.engine.sleep(1.5)
                    continue
                if st.get("rows") or st.get("noData") or st.get("empty"):
                    ready = True
                    break
            self.engine.sleep(1.5)
        if ready:
            self.engine.log("  查询结果已刷新")
        else:
            self.engine.log("  等待结果超时，按当前画面截图")
        return ""

    def read_state(self, page) -> dict:
        try:
            r = page.evaluate(CC_STATE_JS)
        except Exception:
            return {}
        return r if isinstance(r, dict) else {}
