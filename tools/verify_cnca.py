# -*- coding: utf-8 -*-
"""CNCA 真机验证：跑完整链路并在关键节点截图。

三处极验需要人工过，脚本会在每次弹层出现时暂停并提示。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca_run")
COMPANY = "中瑞盛世（北京）建筑有限公司"


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", shot_mode="raw",
                 log=print, manual_timeout=600)
    results = eng.run([COMPANY], ["cnca_list", "cnca_detail"])
    print("\n===== 结果 =====")
    for r in results:
        print("  [%s] %-44s ok=%s %s" % (r.no, r.title, r.ok, r.message or ""))
    ok = sum(1 for r in results if r.ok)
    print("\n成功 %d / %d" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
