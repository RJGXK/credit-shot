# -*- coding: utf-8 -*-
"""探针：探测 全国认证认可信息公共服务平台 (CNCA) 的页面结构与多级查询交互。

平台网址：https://cx.cnca.cn/CertECloud/index/index/page

探测要点：
1. 首页检索框与查询按钮（点击查询后是否弹验证码）；
2. 验证码机制（图形验证码 / 滑块 / 点选，选择器与刷新方式）；
3. 搜索后进入的「认证结果综合查询」界面结构；
4. 「组织列表」tab/按钮，点击后展开证书列表的交互；
5. 点击证书项查看「详细信息」的交互和弹窗/新页结构。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

TARGET = "https://cx.cnca.cn/CertECloud/index/index/page"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)


DUMP_HOME = """
()=>{
  const out = {};
  out.title = document.title;
  out.url = location.href;
  // 查找所有输入框
  out.inputs = [...document.querySelectorAll('input:not([type=hidden]),textarea')].map(e=>({
    id: e.id, name: e.name, cls: e.className, ph: e.placeholder,
    w: e.offsetWidth, h: e.offsetHeight
  }));
  // 查找搜索/查询按钮
  out.buttons = [...document.querySelectorAll('button,a,div,span')].filter(e=>{
    const t = (e.innerText||'').trim();
    return /查询|搜索|检 索|查 询/.test(t) && e.offsetWidth > 10;
  }).map(e=>({
    tag: e.tagName, id: e.id, cls: e.className, txt: (e.innerText||'').trim().slice(0,30),
    onclick: String(e.onclick)
  }));
  return out;
}
"""

def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        print("打开 CNCA 首页：%s" % TARGET)
        page.goto(TARGET, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4.0)

        info = page.evaluate(DUMP_HOME)
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2))
        shot = os.path.join(OUT, "01_home.png")
        page.screenshot(path=shot)
        print("首页截图：", shot)
    finally:
        try: bs.close()
        except Exception: pass

if __name__ == "__main__":
    main()
