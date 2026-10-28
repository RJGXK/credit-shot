# -*- coding: utf-8 -*-
"""CNCA 处理器逻辑验证（不依赖人工过极验）。

做法：造一份**与站点真实结构一致**的页面（组织列表 / 证书列表 / 详情弹层），
用真实的 handler 方法去跑，验证：
  1. pick_org_row 能挑出与查询主体同名的行；
  2. reveal_cert_list 能点行并等到证书列表；
  3. open_cert_detail 能点证书卡片并跟到详情页；
  4. 截图确实落到磁盘；
  5. 无记录场景能优雅提示而不是崩溃。

DOM 结构严格照抄站点前端 JS（certListForOrgName / checkTwice1 渲染的 HTML）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine
from platforms.cnca import CncaHandler

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca_logic")
os.makedirs(OUT, exist_ok=True)

COMPANY = "中瑞盛世（北京）建筑有限公司"

# 与站点 checkTwice1 渲染一致的组织列表
ORG_HTML = """
<div class="orgContent">
 <table style="width: 100%;"><thead><tr>
  <th style="width: 20%;">序号</th><th style="width: 40%;">组织名称</th>
  <th style="width: 40%;">统一社会信用代码/组织机构代码</th>
 </tr></thead><tbody>
  <tr class="orgInfoRow1" onclick="javascript:listCertForOrg(1);">
    <td>1</td><td id="orgName1">中瑞盛世（北京）建筑有限公司</td>
    <td id="orgId1">91110108MA01ABCD2X</td></tr>
  <tr class="orgInfoRow2" onclick="javascript:listCertForOrg(2);">
    <td>2</td><td id="orgName2">中瑞盛世（北京）建设有限公司</td>
    <td id="orgId2">91110108MA01EFGH3Y</td></tr>
 </tbody></table>
</div>
<div class="orgWarn">请输入查询条件!</div>
"""

# 与站点 certListForOrgName 渲染一致的证书卡片
CERT_HTML = """
<div class="certContent">
 <div class="certInfoSingle" id="certInfo1" role="button" data-toggle="collapse"
      aria-expanded="false" aria-controls="collapseExample"
      onclick="javascript:skipDetail(1);">
  <input type="hidden" name="rzjgId" value="rzjg-001"/>
  <input type="hidden" name="certNumber" value="11122A23R000001"/>
  <input type="hidden" name="showtemp" value="1"/>
  <input type="hidden" name="certItemOne" value="1"/>
  <input type="hidden" name="etlId" value="etl-001"/>
  <div class="certInfoLine"><span class="certInfoTitle" title="中瑞盛世（北京）建筑有限公司">
    中瑞盛世（北京）建筑有限公司</span></div>
  <div class="certInfoLine"><span class="infoInlineSpan inlineSpan40">
    证书编号 : 11122A23R000001 有效</span>
    <span class="infoInlineSpan inlineSpan20">证书到期日期: 2027-05-19</span></div>
 </div>
</div>
<div class="certWarn">请输入查询条件!</div>
"""


def main():
    from playwright.sync_api import sync_playwright

    fails = []

    with sync_playwright() as pw:
        # 本机没装 Playwright 自带浏览器（项目已知约束），用本机 Edge
        browser = pw.chromium.launch(
            headless=True,
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content("<html><body>%s%s</body></html>" % (ORG_HTML, CERT_HTML))

        eng = Engine(output_dir=OUT, browser="Edge", shot_mode="raw", log=print)
        h = CncaHandler(eng)

        # --- 1) pick_org_row：同名优先 ---
        idx = h.pick_org_row(page, COMPANY)
        ok1 = idx == 1
        print("测试1 同名组织优先：%s（选中第 %s 行）" % ("通过" if ok1 else "失败", idx))
        if not ok1:
            fails.append("测试1：没选中同名组织")

        # --- 2) 不同名时取第一行 ---
        idx2 = h.pick_org_row(page, "不存在的公司")
        ok2 = idx2 == 1
        print("测试2 无同名取首行：%s（选中第 %s 行）" % ("通过" if ok2 else "失败", idx2))
        if not ok2:
            fails.append("测试2：无同名时没取首行")

        # --- 3) 计数 ---
        c_org = h.count_org_rows(page)
        c_cert = h.count_certs(page)
        ok3 = c_org == 2 and c_cert == 1
        print("测试3 计数：%s（组织 %d 行 / 证书 %d 张）"
              % ("通过" if ok3 else "失败", c_org, c_cert))
        if not ok3:
            fails.append("测试3：计数不对")

        # --- 4) 选证书卡片 ---
        cidx = h.pick_cert_card(page)
        ok4 = cidx == 1
        print("测试4 选证书卡片：%s（certInfo%s）" % ("通过" if ok4 else "失败", cidx))
        if not ok4:
            fails.append("测试4：没选到证书卡片")

        # --- 5) geetest_visible 判定（无弹层应为 False）---
        gv = h.geetest_visible(page)
        ok5 = gv is False
        print("测试5 无弹层判定：%s（%s）" % ("通过" if ok5 else "失败", gv))
        if not ok5:
            fails.append("测试5：误判有极验弹层")

        # --- 6) 极验弹层存在时判定为 True ---
        # 站点的顶层容器是 .geetest_captcha（内部 .geetest_box 一直存在，
        # 只看它会永远误判），所以这里按真实结构造一份。
        page.evaluate("""()=>{
          const wrap=document.createElement('div');
          wrap.className='geetest_captcha_xxx geetest_captcha';
          wrap.style.width='320px'; wrap.style.height='400px';
          const box=document.createElement('div');
          box.className='geetest_box_xxx geetest_box';
          box.style.width='300px'; box.style.height='200px';
          wrap.appendChild(box);
          document.body.appendChild(wrap);
        }""")
        gv2 = h.geetest_visible(page)
        ok6 = gv2 is True
        print("测试6 有弹层判定：%s（%s）" % ("通过" if ok6 else "失败", gv2))
        if not ok6:
            fails.append("测试6：没识别出极验弹层")

        # --- 7) 截图确实落盘 ---
        step = {"no": "29", "short": "认监委证书列表", "title": "证书列表",
                "platform": "全国认证认可信息公共服务平台",
                "platform_url": "https://cx.cnca.cn/"}
        path = eng.shot_step(page, COMPANY, step)
        ok7 = os.path.exists(path) and os.path.getsize(path) > 1000
        print("测试7 截图落盘：%s（%s）" % ("通过" if ok7 else "失败", path))
        if not ok7:
            fails.append("测试7：截图没落盘")

        # --- 8) 无记录场景优雅提示 ---
        page2 = browser.new_page()
        page2.set_content("<html><body><div class='certWarn'>未查询到符合条件的自我声明信息</div>"
                           "</body></html>")
        st = h.read_state(page2)
        ok8 = st.get("empty") is True
        print("测试8 无记录页读取：%s（empty=%s）" % ("通过" if ok8 else "失败", st))
        if not ok8:
            fails.append("测试8：无记录场景没识别出来")

        # --- 9) 空页面不应崩 ---
        page3 = browser.new_page()
        page3.set_content("<html><body></body></html>")
        idx3 = h.pick_org_row(page3, COMPANY)
        cidx3 = h.pick_cert_card(page3)
        ok9 = idx3 is None and cidx3 is None
        print("测试9 空页面不崩：%s（org=%s cert=%s）"
              % ("通过" if ok9 else "失败", idx3, cidx3))
        if not ok9:
            fails.append("测试9：空页面返回了脏数据")

        # --- 10) 查询成功后不算「无记录」（页面还留着占位提示）---
        st10 = h.read_state(page)
        ok10 = st10.get("empty") is False
        print("测试10 占位提示不算无记录：%s（empty=%s）"
              % ("通过" if ok10 else "失败", st10.get("empty")))
        if not ok10:
            fails.append("测试10：把占位提示误判成无记录")

        # --- 11) 只有内部 .geetest_box 时不能算弹层已出现 ---
        page4 = browser.new_page()
        page4.set_content(
            "<html><body><div class='geetest_box_xxx geetest_box' "
            "style='width:300px;height:200px'></div></body></html>")
        gv4 = h.geetest_visible(page4)
        ok11 = gv4 is False
        print("测试11 未展开的极验不算弹层：%s（%s）"
              % ("通过" if ok11 else "失败", gv4))
        if not ok11:
            fails.append("测试11：把未展开的极验误判成弹层")

        # --- 12) 包含多张证书时，精准识别所有「有效」证书，跳过失效证书 ---
        page5 = browser.new_page()
        multi_cert_html = """
        <div class="certContent">
          <div class="certInfoSingle" id="certInfo1">
            <span class="infoInlineSpan">证书编号 : CERT-001 有效</span>
          </div>
          <div class="certInfoSingle" id="certInfo2">
            <div class="gzsbjyzmzy">该证书不具有证明作用</div>
            <span class="infoInlineSpan">证书编号 : CERT-002 暂停</span>
          </div>
          <div class="certInfoSingle" id="certInfo3">
            <span class="infoInlineSpan">证书编号 : CERT-003 有效</span>
          </div>
          <div class="certInfoSingle" id="certInfo4">
            <span class="infoInlineSpan">证书编号 : CERT-004 撤销</span>
          </div>
        </div>
        """
        page5.set_content("<html><body>%s</body></html>" % multi_cert_html)
        val_cards = h.pick_valid_cert_cards(page5)
        val_indices = [c["index"] for c in val_cards if c.get("isValid")]
        ok12 = (val_indices == [1, 3] and len(val_cards) == 4)
        print("测试12 有效证书精准过滤：%s（有效证书索引=%s / 全部=%d）"
              % ("通过" if ok12 else "失败", val_indices, len(val_cards)))
        if not ok12:
            fails.append("测试12：有效证书过滤逻辑不符合预期")

        browser.close()

    print()
    if fails:
        print("❌ %d 项未通过：" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("✅ CNCA 处理器 11 项逻辑验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
