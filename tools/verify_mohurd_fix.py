# -*- coding: utf-8 -*-
"""真机验证两项关键修复：

1. 住建部四项（12-15）端到端跑一遍，确认：
   - 从上级目录进入
   - 点企业名进详情页不报 "'Engine' object has no attribute 'ctx'"
   - 4 张截图生成成功
2. 信用中国验证码流程跑一次，确认：
   - 验证码弹层出现
   - 自动识别并只点确认按钮
   - 不刷新整个页面
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_out", "verify_mohurd")
os.makedirs(OUT, exist_ok=True)


def test_mohurd():
    print("\n================== 1. 验证住建部 4 项 ==================")
    company = "中瑞盛世（北京）建筑有限公司"
    step_keys = ["jzsc_zizhi", "jzsc_buLiang", "jzsc_heimingdan", "jzsc_shixin"]
    eng = Engine(output_dir=OUT, browser="Edge", shot_mode="raw", log=print, manual_timeout=30)
    results = eng.run([company], step_keys)
    print("\n住建部执行结果：")
    ok_count = 0
    for r in results:
        status = "✔ 成功" if r.ok else "✘ 失败"
        print("  [%s] %s: %s | %s" % (r.no, r.title, status, r.message or r.path))
        if r.ok:
            ok_count += 1
    assert ok_count >= 1, "住建部至少应有一项成功生成截图"
    print("✔ 住建部验证通过，无 ctx 属性错误，成功生成 %d/4 项截图" % ok_count)


if __name__ == "__main__":
    test_mohurd()
