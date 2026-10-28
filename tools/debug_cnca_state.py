# -*- coding: utf-8 -*-
"""调试 CNCA read_state：看主仿真页返回的 empty 为什么是 True。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine
from platforms.cnca import CncaHandler, PLACEHOLDER

HTML = ("<html><body>"
        "<div class='orgWarn'>请输入查询条件!</div>"
        "<div class='certWarn'>请输入查询条件!</div>"
        "</body></html>")

RAW = """()=>{
  const txt=(sel)=>{
    const e=document.querySelector(sel);
    return e?((e.innerText||e.textContent||'').trim()):'';};
  const orgWarn=txt('.orgWarn');
  const certWarn=txt('.certWarn');
  return {orgWarn:orgWarn, certWarn:certWarn,
          idxOrg:orgWarn.indexOf('%s'),
          idxCert:certWarn.indexOf('%s')};
}""" % (PLACEHOLDER, PLACEHOLDER)


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(
            headless=True,
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
        page = b.new_page()
        page.set_content(HTML)
        print("RAW:", page.evaluate(RAW))
        eng = Engine(output_dir=os.path.expanduser("~/tmp_cnca"), browser="Edge",
                     shot_mode="raw", log=print)
        h = CncaHandler(eng)
        print("read_state:", h.read_state(page))
        b.close()


if __name__ == "__main__":
    main()
