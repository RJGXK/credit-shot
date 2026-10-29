# -*- coding: utf-8 -*-
"""中国裁判文书网 —— 中国裁判文书网：诉讼 / 仲裁 / 行贿。含高级检索、曾用名分别检索、身份证号二次全文检索、登录后自动重检索。

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

WS_HOME = "https://wenshu.court.gov.cn/"

WS_ADV_CLS = ".advenced-search"

WS_STATE_JS = """
(()=>{
  const body=document.body.innerText||'';
  const rows=document.querySelectorAll('tr').length;
  const noResult=/没有找到|未找到|无相关|没有检索到|暂无数据/.test(body);
  const hasList=document.querySelectorAll('.list-item, .doc-list tr, .list tr').length;
  const hello=(body.match(/欢迎您[，,]\\s*([0-9*]+)/)||[])[1]||'';
  const login=!!hello;
  const needLogin=/请先登录|需要登录/.test(body.slice(0,600));
  const title=document.title||'';
  const loginPage=/登录|注册/.test(title) && body.length<1200;
  const counts=(body.match(/共\\s*\\d+\\s*[条页篇]/g)||[]).slice(0,4).join(', ');
  return {rows:rows, hasList:hasList, noResult:noResult, login:login,
          hello:hello, needLogin:needLogin, loginPage:loginPage, counts:counts,
          url:location.href, title:title,
          snippet:body.replace(/\\n+/g,' | ').slice(0,260)};
})()
"""

WS_FILL_JS = """
(arg)=>{
  const norm=(s)=>(s||'').replace(/\\s+/g,'');
  const findByLabel=(txt)=>{
    const inputs=[...document.querySelectorAll('input,textarea')]
      .filter(x=>x.getClientRects().length);
    for(const inp of inputs){
      let p=inp;
      for(let i=0;i<5 && p;i++){
        p=p.parentElement;
        if(!p) break;
        const t=norm(p.innerText);
        if(t.indexOf(norm(txt))>=0){
          const others=[...p.querySelectorAll('input,textarea')].filter(x=>x!==inp);
          if(others.length===0) return inp;
        }
      }
    }
    return null;
  };
  const set=(el,v)=>{
    if(!el) return 'NO_FIELD';
    el.focus();
    const proto=(el.tagName==='TEXTAREA')?HTMLTextAreaElement:HTMLInputElement;
    const d=Object.getOwnPropertyDescriptor(proto.prototype,'value');
    d.set.call(el,v);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    return 'OK';
  };
  const out={};
  const ids=arg.ids||{};
  for(const k of Object.keys(arg.fields||{})){
    let el=findByLabel(k);
    if(!el && ids[k]){
      const alt=document.querySelector(ids[k]);
      if(alt && alt.getClientRects().length) el=alt;
    }
    let v=arg.fields[k];
    // 追加模式：保留原有条件，关键词用空格连接（裁判文书网全文检索为「与」关系），
    // 这样「先搜主体、再搜案件类型」不会把主体条件冲掉。
    if(arg.appendKeys && arg.appendKeys.indexOf(k)>=0 && el){
      const old=(el.value||'').trim();
      if(old && old.indexOf(v)<0) v=old+' '+v;
    }
    out[k]=set(el,v);
    if(el){ out[k+'_id']=el.id||''; out[k+'_value']=el.value; }
  }
  if(arg.click){
    const btn=[...document.querySelectorAll('button,a,div[class*=btn],span[class*=btn]')]
      .find(e=>norm(e.innerText)===norm(arg.btn) && e.getClientRects().length);
    out.btn = btn ? 'CLICKED' : 'NOT_FOUND';
    if(btn) btn.click();
  }
  return out;
}
"""


class WenshuHandler(PlatformHandler):
    """中国裁判文书网 的采集处理器。"""

    def build_conditions(self, page) -> str:
        """读出页面上的「已选条件」chip，用于确认案件类型确实生效。"""
        try:
            r = page.evaluate("""
            (()=>{
              const t=document.body.innerText||'';
              const m=t.match(/已选条件[\\s\\S]{0,300}/);
              return m?m[0].replace(/\\n+/g,' | ').slice(0,260):'';
            })()""")
        except Exception:
            return ""
        return r if isinstance(r, str) else ""

    def open_advanced_search(self, page) -> bool:
        """从首页进入「高级检索」表单（失败自动重试，最多 3 轮）。

        首页的「高级检索 ▾」是背景图，必须按类名取坐标后用真实鼠标点击。

        站点会自己从 ``/`` 跳到 ``/website/wenshu/<随机ID>/index.html``，
        这个跳转会把 page.goto 打断并抛异常（Navigation ... interrupted by
        another navigation）。所以这里用 core.nav.goto 统一处理，
        跳到哪算哪，不当成失败。

        用户日志里出现过「高级检索表单未展开」一次失败就整个采集项挂掉：
        首页资源慢时入口元素还没渲染出来 —— 所以加多轮重试，
        每轮失败后重新等首页再点。
        """
        self.engine.log("  打开裁判文书网首页…")
        try:
            nav.goto(page, WS_HOME, timeout_ms=self.engine.timeout * 1000,
                     log=self.engine.log)
        except Exception as exc:
            self.engine.log("  ✘ 首页打开失败：%s" % str(exc).splitlines()[0][:90])
            return False
        for rnd in range(1, 4):
            self.engine.sleep(5.0 if rnd == 1 else 4.0)
            box = page.evaluate("""(cls)=>{
                const d=document.querySelector(cls);
                if(!d) return null;
                const b=d.getBoundingClientRect();
                if(b.width<10||b.height<10) return null;
                return {x:b.x+b.width/2, y:b.y+b.height/2};
            }""", WS_ADV_CLS)
            if not box:
                self.engine.log("  ⚠ 首页未找到「高级检索」入口（第 %d 次），稍后重试" % rnd)
                self.engine.sleep(3.0)
                continue
            page.mouse.click(box["x"], box["y"])
            self.engine.sleep(2.5)
            deadline = time.time() + 20
            while time.time() < deadline:
                vis = page.evaluate("""()=>{
                    const i=document.querySelector('#s17');
                    return !!(i && i.getClientRects().length);}""")
                if vis:
                    self.engine.log("  ✔ 已进入高级检索表单")
                    return True
                self.engine.sleep(0.6)
            self.engine.log("  ⚠ 高级检索表单未展开（第 %d 次），重新点入口" % rnd)
        self.engine.log("  ✘ 高级检索表单未能展开（已重试 3 次）")
        return False

    def search(self, page, fields: dict, ids: dict = None) -> dict:
        """在高级检索表单里填条件并点【检索】。

        fields 的键是页面上的标签文字（当事人 / 全文检索），按标签反查输入框，
        找不到再退回已知的 input id。
        """
        res = eval_retry(page, WS_FILL_JS, {
            "fields": fields, "ids": ids or {}, "click": True, "btn": "检索"})
        if not isinstance(res, dict):
            res = {}
        for k in fields:
            state = res.get(k)
            if state == "OK":
                self.engine.log("  ✔ 已填「%s」= %s%s"
                         % (k, fields[k],
                            ("（%s）" % res[k + "_id"]) if res.get(k + "_id") else ""))
            else:
                self.engine.log("  ⚠ 未找到「%s」输入框" % k)
        self.engine.log("  点【检索】：%s" % res.get("btn", "?")) 
        return res

    def refine_by_fulltext(self, page, keyword: str, party: str = "") -> bool:
        """在结果页再用「全文」搜索一次（人员诉讼/仲裁、行贿走这条路径）。

        party 非空时同时把「当事人」一起补上，避免结果页表单没保留原条件。
        全文字段用「追加」方式写入：原值 + 空格 + 新关键词（站点为「与」关系），
        这样「先按身份证号/主体搜，再搜诉讼/仲裁/行贿」不会丢掉主体条件。
        """
        # 结果页顶部的检索区可能收起着，先把高级检索表单点开
        box = page.evaluate("""(cls)=>{
            const d=document.querySelector(cls);
            if(!d) return null;
            const b=d.getBoundingClientRect();
            if(b.width<10||b.height<10) return null;
            return {x:b.x+b.width/2, y:b.y+b.height/2};}""", WS_ADV_CLS)
        if box:
            page.mouse.click(box["x"], box["y"])
            self.engine.sleep(2.0)
        fields = {"全文检索": keyword}
        ids = {"全文检索": "#qbValue"}
        if party:
            fields["当事人"] = party
            ids["当事人"] = "#s17"
        res = eval_retry(page, WS_FILL_JS, {
            "fields": fields, "ids": ids, "appendKeys": ["全文检索"],
            "click": True, "btn": "检索"})
        ok = isinstance(res, dict) and res.get("全文检索") == "OK"
        self.engine.log("  %s 结果页全文再搜索「%s」%s"
                 % ("✔" if ok else "⚠", keyword,
                    ("（全文条件：%s）" % res.get("全文检索_value")) if ok else ""))
        return ok

    def do_search(self, page, fields: dict, ids: dict = None) -> dict:
        """执行一次高级检索：展开表单 -> 填条件 -> 点检索 -> 等结果。

        未登录时站点会把检索跳到「登录/注册」页；此时：
          - 配了账号密码 -> 先走**自动登录**（账号密码自动填好）；
            若中途出现验证码/滑块，程序挂起等人工在浏览器里补验证码，
            人工点【我已处理，继续截图】后程序继续提交并判定；
          - 自动登录没成功 -> 回落人工挂起，等用户自己登录。
        登录成功后**重新进表单再检索一次**（登录页没有检索条件，直接截图是错的）。
        """
        for attempt in range(2):
            if not self.open_advanced_search(page):
                raise EngineError("未能进入裁判文书网高级检索")
            self.search(page, fields, ids)
            st = self.wait_ready(page)
            if not st.get("loginPage"):
                return st
            if attempt == 0:
                self.engine.log(
                    "  检测到未登录（title=%s url=%s 正文前 120 字：%s）"
                    % (str(st.get("title", ""))[:40],
                       str(st.get("url", ""))[:70],
                       str(st.get("snippet", "")).replace("\n", " ")[:120]))
                if self.engine.auto_login(page, "wenshu", "中国裁判文书网"):
                    continue          # 登录成功 -> 重新检索一次
                self.engine.log("  挂起等待人工登录…")
                self.engine.wait_manual(
                    "裁判文书网需要登录。请在浏览器里完成登录（"
                    "若已配置账号密码，可点击【我已处理，继续截图】后由程序补填）"
                    "，完成后点【我已处理，继续截图】；登录态会保留，下次免登录。")
                self.engine.sleep(3)
                continue
            raise EngineError("裁判文书网未登录")
        return {}

    def wait_ready(self, page, timeout: int = 30) -> dict:
        """等检索结果就绪；返回页面状态（可能显示需要登录）。"""
        deadline = time.time() + timeout
        st = {}
        while time.time() < deadline:
            self.engine.check_stop()
            st = self.read_state(page)
            if st.get("loginPage"):
                return st
            if st.get("hasList") or st.get("noResult") or st.get("rows", 0) > 3:
                return st
            self.engine.sleep(1.5)
        return st

    def ensure_login(self, page, st: dict) -> bool:
        """未登录时挂起等待人工登录；返回是否已登录。"""
        if not st.get("loginPage"):
            return True
        self.engine.wait_manual(
            "裁判文书网需要登录，请在浏览器里完成登录后点【我已处理，继续截图】；"
            "登录态会保留，下次免登录。")
        self.engine.sleep(3)
        st2 = self.read_state(page)
        return not st2.get("loginPage")

    def read_alias_names(self, page) -> list:
        """从结果页里提取「曾用名」。"""
        try:
            text = page.evaluate("()=>document.body.innerText||''")
        except Exception:
            return []
        if not text:
            return []
        out = []
        for pat in (r"曾用名[：:]\s*([^，,、；;）)\n]{2,40})",
                    r"曾用名\s*([^，,、；;）)\n]{2,40})"):
            for m in re.findall(pat, text):
                name = (m or "").strip().strip("（()） \t")
                if name and name not in out:
                    out.append(name)
        return out[:5]

    def collect_group(self, page, company: str, gsteps: list,
                      results: List[StepResult], shots: List[str]) -> None:
        """裁判文书网一组采集项（诉讼/仲裁 或 行贿）的执行入口。"""
        subj = self.subject
        person = bool(subj and subj.mode == MODE_PERSON)
        tag = subj.label() if subj else company

        # 人员模式：诉讼与仲裁共享一次「身份证号」检索，
        # 之后各自在结果页用全文细化（用户要求：搜索出来后全文再搜索诉讼、仲裁）
        if person and all(s.get("ws_flow") == "party" for s in gsteps):
            self.collect_person_group(page, company, gsteps, results, shots, tag)
            return

        for si, step in enumerate(gsteps):
            t0 = time.time()
            try:
                # 节流与停止检查放在 try 里，【跳过此步】只跳当前项
                if si > 0:
                    self.engine.pace("（下一采集项前）")
                self.engine.check_stop()
                self.engine.log("[%s] %s" % (step["no"], step["title"]))
                paths = self.run_step(page, company, step, person)
                for path in paths:
                    shots.append(path)
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          True, path=paths[0] if paths else "",
                                          elapsed=time.time() - t0))
            except Skipped:
                self.engine.log("  ⤼ 本步已跳过")
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          False, message="已跳过"))
            except Aborted:
                raise
            except Exception as exc:
                self.engine.log("  ✘ 本步失败：%s" % exc)
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          False, message=str(exc)[:200]))

    def collect_person_group(self, page, company: str, gsteps: list,
                          results: List[StepResult], shots: List[str], tag: str) -> None:
        """人员模式：一次「当事人=姓名 + 全文=身份证号」检索，随后逐个案件类型细化。"""
        subj = self.subject
        name = (subj.person if subj else "").strip()
        idcard = (subj.idcard if subj else "").strip()
        if not name:
            for step in gsteps:
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          False, message="人员模式下没有填人员姓名"))
            return

        searched = False
        for si, step in enumerate(gsteps):
            t0 = time.time()
            try:
                # 节流与停止检查放在 try 里，【跳过此步】只跳当前项
                if si > 0:
                    self.engine.pace("（下一采集项前）")
                self.engine.check_stop()
                self.engine.log("[%s] %s" % (step["no"], step["title"]))
                if not searched:
                    self.engine.log("  当事人「%s」+ 全文「%s」" % (name, idcard or "-"))
                    self.do_search(page, {"当事人": name, "全文检索": idcard},
                                       {"当事人": "#s17", "全文检索": "#qbValue"})
                    searched = True
                self.engine.log("  结果页用全文搜索「%s」" % step.get("case", ""))
                self.refine_by_fulltext(page, step.get("case", ""), party=name)
                self.engine.sleep(4)
                st = self.wait_ready(page, timeout=20)
                self.log_state(page, st)
                path = self.engine.shot_step(page, company, step)
                shots.append(path)
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          True, path=path, elapsed=time.time() - t0))
            except Skipped:
                self.engine.log("  ⤼ 本步已跳过")
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          False, message="已跳过"))
            except Aborted:
                raise
            except Exception as exc:
                self.engine.log("  ✘ 本步失败：%s" % exc)
                results.append(StepResult(step["no"], step["key"], step["title"], tag,
                                          False, message=str(exc)[:200]))

    def run_step(self, page, company: str, step: dict, person: bool) -> list:
        """执行一个裁判文书网采集项，返回生成的截图路径列表。

        单位：当事人 = 单位完整名称，全文 = 案件类型；结果里有曾用名则分别再查一次。
        行贿：全文 = 单位 / 人员 -> 搜索出结果 -> 全文再搜索「行贿」。
        """
        subj = self.subject
        case = step.get("case", "")
        flow = step.get("ws_flow", "party")
        paths = []

        if flow == "fulltext":
            # 全文 = 单位 / 人员 -> 搜索出结果 -> 全文再搜索「行贿」
            subject = (subj.person if person else company).strip()
            if not subject:
                raise EngineError("没有填查询主体，无法查询")
            self.engine.log("  全文检索「%s」" % subject)
            self.do_search(page, {"全文检索": subject}, {"全文检索": "#qbValue"})
            if not self.refine_by_fulltext(page, case):
                self.engine.log("  ⚠ 全文再搜索未生效，按当前结果页截图")
            self.engine.sleep(4)
            st = self.wait_ready(page, timeout=20)
            self.log_state(page, st)
            paths.append(self.engine.shot_step(page, company, step))
            return paths

        # ---- 单位：当事人 = 单位完整名称，全文 = 案件类型 ----
        full_name = company.strip()
        if not full_name:
            raise EngineError("没有填企业名称，无法查询")
        self.engine.log("  当事人「%s」+ 全文「%s」" % (full_name, case))
        self.do_search(page, {"当事人": full_name, "全文检索": case},
                           {"当事人": "#s17", "全文检索": "#qbValue"})
        st = self.wait_ready(page, timeout=20)
        self.log_state(page, st)
        paths.append(self.engine.shot_step(page, company, step))

        # 曾用名：结果里出现就分别再查一次
        aliases = self.read_alias_names(page)
        if aliases:
            self.engine.log("  检测到曾用名：%s —— 分别再查一次" % "、".join(aliases))
            for alias in aliases:
                self.engine.check_stop()
                self.engine.pace("（曾用名检索前）")
                try:
                    self.engine.log("  曾用名「%s」+ 全文「%s」" % (alias, case))
                    self.do_search(page, {"当事人": alias, "全文检索": case},
                                       {"当事人": "#s17", "全文检索": "#qbValue"})
                    self.wait_ready(page, timeout=20)
                    sub = dict(step)
                    sub["short"] = "%s(曾用名%s)" % (step["short"], safe_name(alias))
                    paths.append(self.engine.shot_step(page, company, sub))
                except Aborted:
                    raise
                except Exception as exc:
                    self.engine.log("  ⚠ 曾用名「%s」检索失败：%s" % (alias, exc))
        return paths

    def log_state(self, page, st: dict) -> None:
        """把结果条数与「已选条件」写进日志，便于核对检索是否真的生效。"""
        if not st:
            return
        if st.get("counts"):
            self.engine.log("  检索结果：%s" % st.get("counts"))
        if st.get("noResult"):
            self.engine.log("  页面提示：没有检索到相关文书")
        cond = self.build_conditions(page)
        if cond:
            self.engine.log("  页面检索条件：%s" % cond)

    def read_state(self, page) -> dict:
        try:
            r = page.evaluate(WS_STATE_JS)
        except Exception:
            return {}
        return r if isinstance(r, dict) else {}
