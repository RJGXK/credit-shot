# -*- coding: utf-8 -*-
"""军队采购网 —— 军队采购网：全部/预警/暂停/失信/政府采购失信五类名单（单位 + 专家个人）。

本模块只包含「这个站点怎么查」的知识；
浏览器、页面动作、截图这些通用能力在 core 包里。
所有方法体都是原 engine.py 逐字搬迁，只改了 self 引用的归属。
"""
from __future__ import annotations

import time, re

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

PLAP_STATE_JS = """
(()=>{
  const body=document.body.innerText||'';
  let rows=0, firstRow='';
  document.querySelectorAll('table tr').forEach(tr=>{
    const t=(tr.innerText||'').replace(/\\s+/g,' ').trim();
    if(t.length>6){rows++; if(!firstRow) firstRow=t.slice(0,140);}
  });
  const empty=/没有查询到相关记录|无相关记录|暂无数据|未查询到/.test(body);
  const receipt=/本次查询的关键字|本次查询的时间|本次查询的统一社会信用代码/.test(body);
  const kw=(document.getElementById('handleSearchAllParam')||{}).value||'';
  const active=(document.querySelector('.sonChannelSpan.active')||{}).innerText||'';
  return {rows:rows, firstRow:firstRow, empty:empty, receipt:receipt,
          keyword:kw, active:(active||'').trim(),
          snippet:body.replace(/\\n+/g,' | ').slice(0,240)};
})()
"""


class PlapHandler(PlatformHandler):
    """军队采购网 的采集处理器。"""

    def collect_group(self, page, company: str, gsteps: list,
                    results: List[StepResult], shots: List[str]) -> None:
        """军队采购网：一次进入页面，然后逐个名单切 tab 查询并截图。"""
        try:
            self.prepare(page)
        except Aborted:
            raise
        except Exception as exc:
            self.engine.log("  ✘ 页面打开失败：%s" % str(exc).splitlines()[0])
            for step in gsteps:
                results.append(StepResult(step["no"], step["key"], step["title"], company,
                                          False, message=str(exc)))
            return
        for si, step in enumerate(gsteps):
            t0 = time.time()
            try:
                # 节流与停止检查放在 try 里，【跳过此步】只跳当前项
                if si > 0:
                    self.engine.pace("（下一采集项前）")
                self.engine.check_stop()
                self.engine.log("[%s] %s" % (step["no"], step["title"]))
                self.switch_and_query(page, company, step["tab"])
                path = self.engine.shot_step(page, company, step)
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

    def prepare(self, page):
        self.engine.log("打开军队采购网：%s" % HOME_URLS["plap"])
        # 从上级目录跳转进入（直连易被判异常 IP）
        nav.goto_via_landing(page, "plap", log=self.engine.log,
                             timeout_ms=self.engine.timeout * 1000)
        try:
            nav.goto(page, HOME_URLS["plap"],
                     timeout_ms=self.engine.timeout * 1000, log=self.engine.log,
                     referer=nav.site_referer("plap"))
        except Exception as exc:
            self.engine.log("  ⚠ 打开目标页异常：%s" % str(exc).splitlines()[0][:80])
        self.wait_ready(page, "()=>!!document.getElementById('handleSearchAllParam')", timeout=30)
        self.engine.sleep(2.0)

    def switch_and_query(self, page, company: str, label: str) -> str:
        """切名单 -> 填关键字 -> 查询 -> 等结果。

        军队采购网有两套查询表单：
          顶部关键字框  #handleSearchAllParam（请输入关键字，如供应商名称等）
          失信名单表单  #creditNameId（供应商/专家名称）
                        #creditCodeId（统一社会信用代码/身份证号码）
                        #creditTypeId（处理主体类型：全部/供应商/专家）
        填了人员姓名时走后者（按专家个人查），否则走前者（按供应商名称查）。
        """
        try:
            loc = page.locator(".sonChannelSpan", has_text=re.compile(r"^\s*%s\s*$" % re.escape(label)))
            loc.first.click(timeout=12000)
        except Exception as exc:
            self.engine.log("  名单「%s」切换失败：%s" % (label, str(exc).splitlines()[0]))
            return ""
        self.engine.sleep(3.5)

        subj = self.subject
        use_person = bool(subj and subj.has_person)

        if use_person:
            # 专家个人查询：处理主体类型选「专家」+ 姓名 + 身份证号
            type_ok = self.select_type(page, "专家")
            ok1 = self.fill_field(page, "creditNameId", subj.person.strip())
            ok2 = True
            if subj.idcard.strip():
                ok2 = self.fill_field(page, "creditCodeId", subj.idcard.strip())
            self.engine.log("  按专家个人查询：主体类型=%s 姓名=%s 身份证号=%s"
                     % ("专家" if type_ok else "未选中",
                        subj.person.strip(), subj.idcard.strip()))
            self.engine.log("  填入结果：姓名%s 身份证号%s"
                     % ("成功" if ok1 else "失败", "成功" if ok2 else "失败"))
            if not type_ok:
                self.engine.log("  ⚠ 「处理主体类型」未选中专家，站点表单可能拦下查询")
        else:
            # 军队采购网有两个关键字框，按当前可见的那个填：
            #   #handleSearchAllParam（请输入关键字，如供应商名称等）
            #   #handleSearchParam  （请输入关键字）
            ok = self.fill_keyword(page, company)
            if not ok:
                self.engine.log("  关键字框定位/填入失败")
                return ""
            self.engine.log("  按供应商名称查询：%s" % company)

        page.evaluate("()=>{const bs=[...document.querySelectorAll('a,button,input[type=button],input[type=submit]')]"
                      ".filter(b=>(b.innerText||b.value||'').replace(/\\s+/g,'')==='查询');"
                      "if(bs.length) bs[0].click();}")
        self.engine.sleep(3.0)

        deadline = time.time() + self.engine.timeout
        while time.time() < deadline:
            self.engine.check_stop()
            st = self.read_state(page)
            if st.get("rows", 0) > 0 or st.get("empty") or st.get("receipt"):
                self.engine.log("  结果已刷新（%s）" % (st.get("firstRow") or "无相关记录"))
                return ""
            self.engine.sleep(1.5)
        self.engine.log("  等待结果超时，按当前画面截图")
        return ""

    def fill_field(self, page, element_id: str, value: str) -> bool:
        """填军队采购网表单里某个框（只填有实际尺寸的那个）。"""
        usable = page.evaluate(
            "(id)=>{const e=document.getElementById(id);"
            "if(!e) return false; const r=e.getBoundingClientRect();"
            "return r.width>0 && r.height>0;}", element_id)
        if not usable:
            return False
        return bool(fill_controlled(page, "()=>document.getElementById('%s')" % element_id, value)
                    or set_native(page, "()=>document.getElementById('%s')" % element_id, value))

    def fill_keyword(self, page, company: str) -> bool:
        """填军队采购网的关键字框。

        实测（5 个名单 tab）：
          #handleSearchParam   「请输入关键字」——失信名单表单里真正可填的框
          #handleSearchAllParam「请输入关键字，如供应商名称等」——只在「全部」tab 存在，
                               切到名单 tab 后 rect 为 (0,0,0,0)，填不进去
        所以这里按「有实际尺寸」来挑框，尺寸为 0 的直接跳过。
        """
        ids = ["handleSearchParam", "handleSearchAllParam"]
        for _ in range(3):
            for iid in ids:
                usable = page.evaluate(
                    "(id)=>{const e=document.getElementById(id);"
                    "if(!e) return false; const r=e.getBoundingClientRect();"
                    "return r.width>0 && r.height>0;}", iid)
                if not usable:
                    continue
                ok = (fill_controlled(page, "()=>document.getElementById('%s')" % iid, company)
                      or set_native(page, "()=>document.getElementById('%s')" % iid, company))
                if ok:
                    return True
            self.engine.sleep(1.2)   # tab 可能还没切换完，稍等再试
        return False

    def select_type(self, page, label: str) -> bool:
        """选择「处理主体类型」下拉（全部/供应商/专家）。

        实测：这是 layui 渲染的原生 <select>——原生 select 本身被隐藏
        （getBoundingClientRect 为 0x0），页面上看到的是 layui 自绘的假下拉。
        所以**不能**用可见性判断，否则永远选不中；直接设 value 再 dispatch change，
        layui 会把显示文本同步过来。
        该字段带 lay-verify="required"，为空时表单校验会直接拦下查询。
        """
        try:
            return bool(page.evaluate("""
            (arg)=>{
              const e=document.getElementById('creditTypeId');
              if(!e) return false;
              const opt=[...e.options].find(o=>(o.textContent||'').trim()===arg.label);
              if(!opt) return false;
              e.value=opt.value;
              e.dispatchEvent(new Event('change',{bubbles:true}));
              return e.value===opt.value;
            }""", {"label": label}))
        except Exception:
            return False

    def read_state(self, page) -> dict:
        try:
            r = page.evaluate(PLAP_STATE_JS)
        except Exception:
            return {}
        return r if isinstance(r, dict) else {}
