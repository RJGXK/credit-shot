# -*- coding: utf-8 -*-
"""真机验证截图降级策略。

场景：
  1) 普通页面整页截图；
  2) 超长页面（6000px）整页截图；
  3) 超长页面 + sticky 元素（gsxt 详情页那种左侧导航）；
  4) 信息条模式（插入信息条后整页截图）。

每种都要能产出图片，且文件大小 > 0。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capture import capture
from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "shots")

HTML_TALL = """<!doctype html><html><head><meta charset="utf-8">
<style>
 body{font:15px/1.8 "Microsoft YaHei",sans-serif;margin:0;padding:20px}
 .box{border:1px solid #ccc;padding:16px;margin:10px 0;background:#fff}
 .side{position:sticky;top:0;left:0;width:180px;height:120px;background:#124a9b;color:#fff}
 .top{position:fixed;top:0;right:0;width:200px;height:40px;background:#0b3a80;color:#fff}
</style></head><body>
<div class="top">固定顶栏</div>
<div class="side">粘性侧栏</div>
<div class="box">顶部内容</div>
""" + "".join('<div class="box">第 %d 段内容 —— 用于把页面撑到很长，测试整页截图的拼接与降级</div>' % i
              for i in range(1, 140)) + """
<div class="box">底部内容</div>
</body></html>"""


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=print)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        html_path = os.path.join(OUT, "tall.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(HTML_TALL)
        page.goto("file:///" + html_path.replace("\\", "/"), wait_until="load")
        time.sleep(1.5)
        h = page.evaluate("()=>document.body.scrollHeight")
        print("页面总高度:", h)

        step = {"no": "T1", "short": "测试", "title": "截图降级测试",
                "platform": "测试平台", "platform_url": "https://example.com/",
                "unstick": True}

        cases = [
            ("普通整页", "原图", False),
            ("信息条整页", "原图+信息条", False),
            ("sticky解除整页", "原图", True),
        ]
        for name, mode, unstick in cases:
            st = dict(step)
            st["unstick"] = unstick
            path = os.path.join(OUT, "%s.png" % name)
            t0 = time.time()
            try:
                capture(page, path, "测试企业", st, mode, subject=None, log=print)
                size = os.path.getsize(path) if os.path.exists(path) else 0
                print("  %-14s OK  用时 %.1fs  大小 %d KB"
                      % (name, time.time() - t0, size // 1024))
            except Exception as exc:
                print("  %-14s 失败：%s" % (name, str(exc).splitlines()[0][:80]))
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
