# -*- coding: utf-8 -*-
"""中国政府采购网 —— 中国政府采购网：政府采购严重违法失信行为记录名单（必须从首页进入）。

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


class CcggHandler(PlatformHandler):
    """中国政府采购网 的采集处理器。"""

    def collect(self, page, company: str, code: str, step: dict) -> str:
        """政府采购网严重违法失信名单（按要求从首页进入 -> 监督检查 -> 名单页）。"""
        home = step.get("home") or HOME_URLS["ccgp"]
        self.engine.log("从首页进入：%s" % home)
        # 直连政采网会被 WAF 拦（403），先从上级目录跳转
        nav.goto_via_landing(page, "ccgp", log=self.engine.log,
                             timeout_ms=self.engine.timeout * 1000)
        try:
            nav.goto(page, home, timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log)
        except Exception as exc:
            self.engine.log("  ⚠ 打开首页异常：%s" % str(exc).splitlines()[0][:80])
        self.engine.sleep(3.0)

        page.evaluate("()=>{const n=document.querySelector('#ch_jdjc a'); if(n) n.click();}")
        self.engine.sleep(5.0)

        page.evaluate("""
        ()=>{
          const as=[...document.querySelectorAll('a')].filter(e=>
            (e.innerText||'').trim()==='政府采购严重违法失信行为记录名单');
          if(as.length) as[0].click();
        }""")
        self.engine.sleep(6.0)

        cur = ""
        try:
            cur = page.url or ""
        except Exception:
            pass
        if "/cr/list" in cur:
            self.engine.log("  落到 /cr/list，改用 /search/cr/ 入口")
            page.goto(HOME_URLS["ccgp_list"], wait_until="domcontentloaded",
                      timeout=self.engine.timeout * 1000)
            self.engine.sleep(4.0)

        self.wait_ready(page, "()=>!!document.querySelector('iframe')", timeout=25)

        # iframe 与主页面同源，直接在 iframe 文档里填条件并点「查找」
        res = page.evaluate("""
        (arg)=>{
          try{
            const f=document.querySelector('iframe');
            const d=f?f.contentDocument:null;
            if(!d) return 'NO_DOC';
            const set=(id,val)=>{
              const e=d.getElementById(id); if(!e||!val) return false;
              e.focus(); e.select();
              const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
              s.call(e,val);
              e.dispatchEvent(new Event('input',{bubbles:true}));
              e.dispatchEvent(new Event('change',{bubbles:true}));
              return e.value===val;
            };
            const a=set('orgName',arg.name);
            const b=set('orgCode',arg.code);
            // #searchForm 实为 <input type=button value="查找">，必须点它才会检索
            const btn=d.getElementById('searchForm')||
                      [...d.querySelectorAll('input.cr-list-button')].find(x=>x.value==='查找');
            let fired='NO_BTN';
            if(btn){ btn.click(); fired='CLICK:'+(btn.value||btn.innerText||'').trim(); }
            return JSON.stringify({name:a, code:b, fired:fired});
          }catch(e){ return 'ERR:'+e.message; }
        }
        """, {"name": company, "code": code})
        self.engine.log("  填写并提交：%s" % str(res)[:160])

        deadline = time.time() + self.engine.timeout + 40
        prev_first = ""
        while time.time() < deadline:
            self.engine.check_stop()
            try:
                st = page.evaluate("""
                (()=>{
                  const f=document.querySelector('iframe');
                  const d=f?f.contentDocument:null;
                  if(!d||!d.body) return {};
                  const body=d.body.innerText||'';
                  const trs=[...d.querySelectorAll('table tr')];
                  const first=trs.slice(1).map(t=>(t.innerText||'').replace(/\\s+/g,' ').trim().slice(0,60)).filter(Boolean)[0]||'';
                  return {rows:trs.length, first:first,
                    empty:/没有该企业的相关记录|没有找到|无相关|未查询到|暂无|共\\s*0\\s*条|没有符合条件的/.test(body),
                    receipt:/查询内容|查询时间|统一社会信用代码/.test(body),
                    snippet:body.replace(/\\n+/g,' | ').slice(0,240)};
                })()
                """)
            except Exception:
                st = {}
            first = str(st.get("first", ""))
            if first and first != prev_first and "湖北卓亚" not in first:
                self.engine.log("  查询结果已刷新：%s" % first[:60])
                break
            if st.get("empty") and "湖北卓亚" not in first:
                self.engine.log("  查询结果已刷新（无该企业相关记录）")
                break
            self.engine.sleep(2)
        return ""
