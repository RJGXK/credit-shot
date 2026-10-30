# -*- coding: utf-8 -*-
"""失信被执行人 —— 最高法失信被执行人查询（zxgk.court.gov.cn）：单位与人员两种口径。

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

ZX_STATE_JS = """
(()=>{
  const body=document.body.innerText||'';
  const ov=document.querySelector('.tianai-captcha-ui-overlay');
  const overlay=!!(ov && getComputedStyle(ov).display!=='none');
  const blk=document.querySelector('#result-block');
  const tbl=document.querySelector('#result-table');
  const name=(document.getElementById('pName')||{}).value||'';
  const card=(document.getElementById('pCardNum')||{}).value||'';
  return {overlay:overlay, url:location.href,
          hasForm:!!document.getElementById('myform'),
          name:name, card:card,
          blockText:(blk?(blk.innerText||'').replace(/\\s+/g,' ').trim().slice(0,300):''),
          tableRows:tbl?tbl.querySelectorAll('tr').length:0,
          noResult:/没有找到|未找到|无相关|没有查询到|暂无/.test(body),
          snippet:body.replace(/\\n+/g,' | ').slice(0,260)};
})()
"""


class ShixinHandler(PlatformHandler):
    """失信被执行人 的采集处理器。"""

    def collect_dishonest(self, page, company: str, code: str, step: dict) -> str:
        """最高法失信被执行人网查询（天艾点选验证码需人工）。

        表单两个框（实测）：
            #pName      被执行人姓名/名称
            #pCardNum   身份证号码/组织机构代码
        所以「企业名 + 统一社会信用代码」和「人员姓名 + 身份证号」都能查：
        填了人员信息就按个人查，否则按企业查。
        """
        url = step.get("url") or HOME_URLS["zxgk"]
        self.engine.log("打开：%s" % url)
        # 从上级目录跳转进入；**不直接 goto 目标页**（用户要求：从第一步一步步点进去，
        # 直接输网址会被判审核不通过）。进首页后在页面里点「失信被执行人」入口。
        nav.goto_via_landing(page, "zxgk", log=self.engine.log,
                             timeout_ms=self.engine.timeout * 1000)
        r = page.evaluate("""()=>{
          const norm=s=>(s||'').replace(/\\s+/g,'');
          const as=[...document.querySelectorAll('a[href]')]
            .filter(a=>/shixin|失信/.test((a.innerText||'')+ (a.getAttribute('href')||'')));
          const hit=as.find(a=>norm(a.innerText||'').indexOf('失信')>=0) || as[0];
          if(!hit) return 'NONE';
          hit.click();
          return 'CLICK:'+norm(hit.innerText||'').slice(0,20);
        }""")
        self.engine.log("  点进「失信被执行人」：%s" % str(r)[:60])
        if not str(r).startswith("CLICK"):
            self.engine.log("  ⚠ 首页上没找到失信被执行人入口，按当前页继续（不做直连）")
        self.engine.sleep(2.5)
        self.wait_ready(page, "()=>!!document.getElementById('myform')", timeout=30)
        self.engine.sleep(1.5)

        subj = self.subject
        if subj and subj.has_person:
            q_name = subj.person.strip()
            q_id = subj.idcard.strip() or subj.code.strip()
            if not q_name:
                raise EngineError("人员模式下没有填人员姓名，无法查询")
            self.engine.log("按自然人查询：姓名=%s 身份证号=%s" % (q_name, q_id))
        else:
            q_name = company
            q_id = code
            if not q_name:
                raise EngineError("没有填企业名称，无法查询")
            self.engine.log("按企业查询：名称=%s 信用代码=%s" % (q_name, q_id))

        # 该页输入框用原生 setter 赋值会被清空，必须走真实键盘输入
        fill_controlled(page, "()=>document.getElementById('pName')", q_name)
        if q_id:
            fill_controlled(page, "()=>document.getElementById('pCardNum')", q_id)
        filled_name = page.evaluate("()=>{const e=document.getElementById('pName'); return e?e.value:'';}")
        filled_id = page.evaluate("()=>{const e=document.getElementById('pCardNum'); return e?e.value:'';}")
        if (filled_name or "").strip() != q_name:
            raise EngineError("失信被执行人「被执行人姓名/名称」填入失败")
        self.engine.log("已填入：%s%s" % (filled_name, (" / " + filled_id) if filled_id else ""))

        # 点查询 -> 触发天艾点选验证码
        page.evaluate("()=>{const f=document.getElementById('myform'); if(!f) return;"
                      "const b=f.querySelector('button.btn-zxgk')||f.querySelector('button');"
                      "if(b) b.click();}")
        self.engine.sleep(3)

        overlay = self.wait_ready(
            page, "()=>{const o=document.querySelector('.tianai-captcha-ui-overlay');"
                  "return !!(o && getComputedStyle(o).display!=='none');}", timeout=25)
        if overlay:
            self.engine.wait_manual("失信被执行人查询弹出点选验证码，请在浏览器里按提示点选文字完成验证。")
            self.engine.sleep(2)

        deadline = time.time() + self.engine.timeout
        ready = False
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                st = page.evaluate(ZX_STATE_JS)
            except Exception:
                st = {}
            blk = str(st.get("blockText", ""))
            if not st.get("overlay") and ("全国范围内没有找到" in blk or q_name in blk
                                          or st.get("tableRows", 0) > 1 or st.get("noResult")):
                ready = True
                break
            self.engine.sleep(2)
        if ready:
            self.engine.log("  查询结果已刷新")
        else:
            self.engine.log("  等待结果超时，按当前画面截图")
        return ""
