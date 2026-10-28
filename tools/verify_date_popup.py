# -*- coding: utf-8 -*-
"""真机验证日期弹窗的各种场景。

场景：
  1) 浏览器最大化时展开；
  2) 浏览器非最大化（还原）时展开；
  3) 浏览器最小化时展开；
  4) 连开 5 次统计成功率。

判据：_looks_like_calendar() 为真。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop
from engine import Engine

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out")


def try_open(label):
    desktop.wake_taskbar(print)
    ok = desktop.open_date_popup(print)
    print("  %-22s -> %s" % (label, ok))
    desktop.close_date_popup()
    time.sleep(0.8)
    return ok


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", log=lambda s: None)
    try:
        pw, browser, ctx, page = eng.open_browser()
    except Exception as exc:
        print("浏览器启动失败:", exc)
        return
    try:
        time.sleep(2)
        hwnd = desktop.find_browser_window("Edge", "")
        print("找到浏览器窗口:", hwnd)

        print("\n== 1) 最大化 ==")
        if hwnd:
            desktop.activate_window(hwnd, maximize=True)
            time.sleep(1.2)
        try_open("最大化")

        print("\n== 2) 还原 ==")
        if hwnd:
            desktop.activate_window(hwnd, maximize=False)
            time.sleep(1.2)
        try_open("还原")

        print("\n== 3) 最小化 ==")
        if hwnd:
            import win32con
            import win32gui
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass
            time.sleep(1.2)
        try_open("最小化")
        if hwnd:
            desktop.activate_window(hwnd, maximize=True)
            time.sleep(1.0)

        print("\n== 4) 连开 5 次 ==")
        n = 0
        for i in range(5):
            if try_open("第 %d 次" % (i + 1)):
                n += 1
        print("\n成功率: %d/5" % n)
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
