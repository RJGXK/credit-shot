# -*- coding: utf-8 -*-
"""端到端复现：只跑中国裁判文书网那一组（用户日志里报错的那一组）。

验证点：
  1) 首页自跳转不再抛「Navigation ... interrupted」；
  2) 高级检索表单可用；
  3) 检索后能读到「已选条件」（就是原来 build_conditions 崩溃的地方）；
  4) 结果页的二次全文检索不再崩；
  5) 整页截图能出图。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SITES
from engine import Engine
from auth.credentials import load_credentials, load_captcha_key

COMPANY = "中瑞盛世（北京）建筑有限公司"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "e2e_wenshu")

# 只挑裁判文书网的三个采集项（kind == "wenshu"）
keys = [s["key"] for site in SITES
        for s in site.get("steps", []) if s.get("kind") == "wenshu"]
print("本次采集项：", keys)

# 读本机已保存的凭据（走真实自动登录链路）
creds = {c.platform: {"username": c.username, "password": c.password}
         for c in load_credentials()
         if c.enabled and c.username and c.password}
print("已加载凭据的平台：", list(creds.keys()) or "（无）")

os.makedirs(OUT, exist_ok=True)
eng = Engine(output_dir=OUT, shot_mode="原图", subject_mode="company",
             pace_seconds=0, timeout=45, log=print,
             credentials=creds,
             captcha_key=load_captcha_key(),
             manual_timeout=90)   # 无人值守：人工等待时限压到 90 秒

try:
    res = eng.run([COMPANY], keys)
except Exception as exc:
    print("!! 引擎异常：%s" % exc)
    raise

print("\n" + "=" * 60)
for r in res:
    print("  %-6s %-12s %-4s %s"
          % (r.no, r.key, "成功" if r.ok else "失败", (r.message or "")[:60]))
    if r.path:
        print("        → %s" % r.path)
print("产出目录：", OUT)
for f in sorted(os.listdir(OUT)):
    print("   -", f)
