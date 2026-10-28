# -*- coding: utf-8 -*-
"""CNCA 结果页探针（需要人工过一次极验点选）。

流程：
  1. 首页填企业名称 -> 点「查询」；
  2. 极验点选弹层出现 -> 提示人工在浏览器里点完；
  3. 人工回车后，抓「认证结果综合查询」页面的 DOM：
     - 组织列表入口（获证组织名称列）
     - 证书列表表格
     - 「查看详细信息」入口
     - 各阶段验证码输入框
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)

DUMP_JS = """()=>{
  const vis = e => { const b=e.getBoundingClientRect(); return b.width>0&&b.height>0; };
  const out = {};
  out.url = location.href;
  out.title = document.title;
  out.inputs = [...document.querySelectorAll('input')].filter(vis).map(e=>({
      id:e.id, name:e.name, type:e.type,
      ph:e.placeholder, cls:(e.className||'').toString().slice(0,40)}));
  out.tables = [...document.querySelectorAll('table')].map(t=>({
      cls:(t.className||'').toString().slice(0,60),
      headers:[...t.querySelectorAll('th')].map(x=>x.innerText.trim()),
      rows:t.querySelectorAll('tbody tr').length,
      firstRows:[...t.querySelectorAll('tbody tr')].slice(0,3).map(tr=>
        [...tr.querySelectorAll('td')].map(td=>td.innerText.replace(/\\s+/g,' ').trim().slice(0,40)))}));
  // 所有看起来像「详情 / 查看 / 更多」的入口
  out.detailLinks = [...document.querySelectorAll('a,button,span,i,td')]
    .filter(e=>/查看|详情|明细|更多|展开/.test(e.innerText||''))
    .map(e=>({tag:e.tagName, t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,24),
              href:(e.getAttribute('href')||'').slice(0,90),
              onclick:(e.getAttribute('onclick')||'').slice(0,90),
              cls:(e.className||'').toString().slice(0,50)}));
  // 组织名相关的可点元素
  out.orgLinks = [...document.querySelectorAll('a,span,td,div')]
    .filter(e=>{const t=(e.innerText||'').trim();
                return t && t.length>4 && t.length<40 && /公司|集团|有限/.test(t);})
    .map(e=>({tag:e.tagName, t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,36),
              onclick:(e.getAttribute('onclick')||'').slice(0,90),
              cls:(e.className||'').toString().slice(0,50)})).slice(0,20);
  out.btns = [...document.querySelectorAll('button')].filter(vis).map(e=>({
      t:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,20),
      onclick:(e.getAttribute('onclick')||'').slice(0,90)}));
  out.geetest = [...document.querySelectorAll('[class*=geetest_box],[class*=geetest_popup]')]
    .filter(vis).length;
  out.body = (document.body?document.body.innerText:'').replace(/\\n+/g,' | ');
  return out;
}"""


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(TARGET, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        company = "中瑞盛世（北京）建筑有限公司"
        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(e){ e.focus(); e.value=name;
            e.dispatchEvent(new Event('input',{bubbles:true}));
            e.dispatchEvent(new Event('change',{bubbles:true})); }
        }""", company)
        time.sleep(1)
        page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(b) b.click();
        }""")
        time.sleep(5)
        page.screenshot(path=os.path.join(OUT, "e01_geetest.png"))
        print("已点查询，截图：probe_out/cnca/e01_geetest.png")
        print(">>> 请在浏览器里完成极验「请在下图依次点击」验证")
        input("===> 验证完成后按 Enter 继续…")

        time.sleep(4)
        info = page.evaluate(DUMP_JS)
        print("\n===== 结果页 =====")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:7000])
        page.screenshot(path=os.path.join(OUT, "e02_result.png"), full_page=True)
        print("截图：probe_out/cnca/e02_result.png")

        # 若列表已出现，点第一个组织名看看后续
        orgs = page.evaluate("""()=>{
          const cands=[...document.querySelectorAll('a,span,td,div')]
            .filter(e=>{const t=(e.innerText||'').trim();
              return t && t.length>4 && t.length<40 && /公司|集团|有限/.test(t);});
          if(!cands.length) return 'NONE';
          const e=cands.find(x=>x.tagName==='A')||cands[0];
          e.click();
          return (e.innerText||'').trim().slice(0,40);
        }""")
        print("\n点击组织名：", orgs)
        time.sleep(5)
        info2 = page.evaluate(DUMP_JS)
        print("\n===== 点组织名后 =====")
        print(json.dumps(info2, ensure_ascii=False, indent=1)[:7000])
        page.screenshot(path=os.path.join(OUT, "e03_after_org.png"), full_page=True)
        print("截图：probe_out/cnca/e03_after_org.png")
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
