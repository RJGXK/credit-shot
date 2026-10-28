# -*- coding: utf-8 -*-
"""人工过验证码后，继续探测：
1. 认证结果综合查询页面的 URL 和 DOM；
2. 点击「组织列表」后的页面或表格；
3. 展开证书列表（证书编号、体系名称、状态等）；
4. 查看证书详细信息的链接/弹窗/新标签页。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(TARGET, wait_until="networkidle", timeout=45000)
        time.sleep(2)
        company = "中瑞盛世（北京）建筑有限公司"
        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(e){ e.focus(); e.value=name; e.dispatchEvent(new Event('input',{bubbles:true})); }
        }""", company)
        time.sleep(1)
        print("点击查询…")
        page.evaluate("()=>{const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询'); if(b) b.click();}")
        print("请在浏览器里完成极验点选验证码，并在完成后终端回车继续…")
        input("===> 人工点选验证码完成后，按 Enter 键继续探测后续步骤...")
        time.sleep(3)

        # 检查跳转后的页面
        print("当前页面 URL:", page.url)
        print("当前页面标题:", page.title())

        # 分析当前页的 tabs / tables / buttons
        page_info = page.evaluate("""()=>{
          const out = {};
          out.url = location.href;
          out.title = document.title;
          // tabs
          out.tabs = [...document.querySelectorAll('.nav-tabs li, .tabs li, [class*=tab]')].map(e=>e.innerText.trim()).filter(Boolean);
          // 查找「组织列表」
          const orgLinks = [...document.querySelectorAll('a, button, span, li')].filter(e=>/组织列表|企业列表/.test(e.innerText||''));
          out.orgLinks = orgLinks.map(e=>({tag: e.tagName, text: e.innerText.trim(), cls: e.className}));
          // table
          out.tableHeaders = [...document.querySelectorAll('th')].map(t=>t.innerText.trim());
          out.rowsCount = document.querySelectorAll('tbody tr').length;
          return out;
        }""")
        import json
        print("查询后页面结构：", json.dumps(page_info, ensure_ascii=False, indent=2))
        page.screenshot(path="probe_out/cnca/03_result_page.png")
        print("截图：probe_out/cnca/03_result_page.png")
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
