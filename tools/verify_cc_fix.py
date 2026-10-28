# -*- coding: utf-8 -*-
"""真机验证信用中国验证码流程：

采集「cc_shixin」（信用中国失信黑名单）：
  - 走上级目录跳转进入；
  - 填入企业名，点查询；
  - 弹层出现后，自动过验证码（只换图不刷新页面 + 提交 + 判错重试）；
  - 最终结果刷新，生成截图。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_out", "verify_cc")
os.makedirs(OUT, exist_ok=True)


def test_creditchina():
    print("\n================== 2. 验证信用中国验证码闭环 ==================")
    company = "中瑞盛世（北京）建筑有限公司"
    step_keys = ["cc_shixin"]
    eng = Engine(output_dir=OUT, browser="Edge", shot_mode="raw", log=print, manual_timeout=35)
    results = eng.run([company], step_keys)
    print("\n信用中国执行结果：")
    for r in results:
        status = "✔ 成功" if r.ok else "✘ 失败"
        print("  [%s] %s: %s | %s" % (r.no, r.title, status, r.message or r.path))
    assert any(r.ok for r in results), "信用中国应至少有一项成功生成截图"
    print("✔ 信用中国验证通过")


if __name__ == "__main__":
    test_creditchina()
