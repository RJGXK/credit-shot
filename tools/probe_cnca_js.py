# -*- coding: utf-8 -*-
"""从浏览器内部抓 CNCA 的真实 JS 资源（绕过混淆 cookie 加载器）。

页面里的 <script src> 指向的文件如果直接 curl 拿到的是「设置 clearance cookie
再刷新」的混淆壳，必须在浏览器里（已带 cookie）fetch 才能拿到真正的业务代码。

拿到业务代码后就能读出：
  * 提交查询的接口与参数
  * 各阶段验证码输入框的 id 与校验逻辑
  * 组织列表 / 证书列表 / 详细信息的 DOM 与接口
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

# 业务相关的 JS（按探针抓到的清单）
WANT = [
    "/CertECloud/resourses/js/index/index.js",
    "/CertECloud/resourses/js/result/cx_result_list.js",
    "/CertECloud/resourses/js/cx_common.js",
    "/CertECloud/resourses/common/embeddedControl.js",
    "/CertECloud/resourses/js/clientInfoCheck.js",
    "/CertECloud/resourses/geetest/geetest.js",
]


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto(TARGET, wait_until="networkidle", timeout=60000)
        time.sleep(4)

        for path in WANT:
            res = page.evaluate("""async (p)=>{
              try{
                const r = await fetch(p, {credentials:'include'});
                const t = await r.text();
                return {status:r.status, len:t.length, text:t};
              }catch(e){ return {status:-1, len:0, text:'ERR:'+e}; }
            }""", path)
            name = os.path.basename(path).split("?")[0]
            fn = os.path.join(OUT, "js_" + name)
            with open(fn, "w", encoding="utf-8") as f:
                f.write(res.get("text") or "")
            print("%-34s status=%s len=%s -> %s"
                  % (name, res.get("status"), res.get("len"), fn))
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
