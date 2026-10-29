# -*- coding: utf-8 -*-
"""离线比对：哪种「题型 × 预处理 × 调用次数」能把信用中国验证码读对。

样本来自真机（肉眼可读的正确答案标在 EXPECT 里）：
  ocr_1_element.png  C6A1
  verify_cc_1.png    8HUT
  verify_cc_3.png    Q9H0
  fetch2_orig.jpg    59IV（原图 95x25，被站点用 fetch 换过一次，不是当前 session 的）

用法：python tools/probe_cc_modes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.captcha import denoise_captcha          # noqa: E402
from core.yescaptcha import YesCaptcha             # noqa: E402
from auth.credentials import load_captcha_key      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "probe_out")

CASES = [
    ("ocr_1_element.png", "C6A1"),
    ("verify_cc_1.png", "8HUT"),
    ("verify_cc_3.png", "Q9H0"),
    ("fetch2_orig.jpg", "59IV"),
]


def main():
    key = load_captcha_key()
    if not key:
        print("没有 API Key")
        return
    client = YesCaptcha(key, "cn", print)
    stats = {}

    for fn, expect in CASES:
        path = os.path.join(OUT, fn)
        if not os.path.exists(path):
            print("缺少样本 %s" % fn)
            continue
        data = open(path, "rb").read()
        print("\n=== %s（应为 %s）===" % (fn, expect))
        for vname, vdata in (("原样", data), ("去干扰线", denoise_captcha(data))):
            for tname, fn2 in (("同步", client.solve_image_to_text),
                               ("异步", client.solve_image_to_text_async)):
                outs = []
                for _ in range(2):
                    try:
                        outs.append(fn2(vdata))
                    except Exception as exc:
                        outs.append("ERR:%s" % str(exc)[:30])
                key2 = "%s+%s" % (vname, tname)
                stat = stats.setdefault(key2, {"n": 0, "hit": 0, "same": 0})
                stat["n"] += 1
                if outs and outs[0].upper() == expect.upper():
                    stat["hit"] += 1
                if len(set(outs)) == 1:
                    stat["same"] += 1
                print("  %-10s %-4s -> %-40s %s"
                      % (vname, tname, outs, "✔" if outs and outs[0].upper() == expect.upper() else "✘"))

    print("\n===== 汇总 =====")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]["hit"]):
        print("  %-16s 一次读对 %d/%d，结果稳定 %d/%d"
              % (k, v["hit"], v["n"], v["same"], v["n"]))


if __name__ == "__main__":
    main()
