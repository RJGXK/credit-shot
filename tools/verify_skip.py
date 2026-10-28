# -*- coding: utf-8 -*-
"""验证【跳过此步】真正生效。

要验三件事：
  1. **响应时延**：引擎在长等待中点跳过，应该 1 秒内响应（以前要等整段睡完）；
  2. **作用范围**：只跳当前这一步，后面的采集项照常执行；
  3. **不被吞掉**：平台层的 except Exception 不会把跳过信号吃掉。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.control import Control
from core.errors import Aborted, Skipped

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "skip")


class FakeEngine:
    """模拟引擎：三个采集项，每项做一次 30 秒的长等待。"""

    def __init__(self, control):
        self.control = control
        self.log_lines = []
        self.steps_done = []
        self.skipped = []
        self.started = time.time()

    def log(self, msg):
        self.log_lines.append(msg)

    def sleep(self, seconds):
        self.control.wait(seconds)

    def check_stop(self):
        if self.control.stop.is_set():
            raise Aborted()
        if self.control.skip.is_set():
            self.control.skip.clear()
            raise Skipped()

    def run_one(self, idx):
        try:
            self.check_stop()
            self.log("开始第 %d 项" % idx)
            # 模拟页面加载等待（以前是 time.sleep(30)，点了跳过也听不见）
            self.sleep(30)
            self.steps_done.append(idx)
            self.log("第 %d 项完成" % idx)
        except Skipped:
            self.skipped.append(idx)
            self.log("第 %d 项已跳过" % idx)


def main():
    os.makedirs(OUT, exist_ok=True)
    fails = []

    # ---------------- 测试 1：等待中点跳过，1 秒内响应 ----------------
    ctrl = Control()
    eng = FakeEngine(ctrl)

    def click_skip():
        time.sleep(1.0)          # 让引擎先进入等待
        ctrl.request_skip()

    t = threading.Thread(target=click_skip, daemon=True)
    t.start()
    t0 = time.time()
    eng.run_one(1)
    dt = time.time() - t0
    ok1 = eng.skipped == [1] and dt < 3.0
    print("测试1 等待中点跳过：%s（耗时 %.2f 秒，跳过项 %s）"
          % ("通过" if ok1 else "失败", dt, eng.skipped))
    if not ok1:
        fails.append("测试1：响应太慢或没跳过")

    # ---------------- 测试 2：只跳当前项，后续继续 ----------------
    ctrl2 = Control()
    eng2 = FakeEngine(ctrl2)

    def click_skip2():
        time.sleep(1.0)
        ctrl2.request_skip()

    threading.Thread(target=click_skip2, daemon=True).start()
    for i in (1, 2, 3):
        try:
            eng2.run_one(i)
        except Skipped:
            eng2.skipped.append(i)
    ok2 = eng2.skipped == [1]
    print("测试2 只跳当前项：%s（跳过 %s，完成 %s）"
          % ("通过" if ok2 else "失败", eng2.skipped, eng2.steps_done))
    if not ok2:
        fails.append("测试2：跳过后没继续执行后续项")

    # ---------------- 测试 3：except Exception 抓不住跳过信号 ----------------
    ctrl3b = Control()
    eng3b = FakeEngine(ctrl3b)
    ctrl3b.request_skip()
    caught = []
    try:
        try:
            eng3b.check_stop()
        except Exception as exc:
            caught.append("SWALLOWED_BY_EXCEPT_EXCEPTION:%r" % (exc,))
    except Skipped:
        caught.append("Skipped")
    ok3 = caught == ["Skipped"]
    print("测试3 跳过不被 except Exception 吞掉：%s（%r）"
          % ("通过" if ok3 else "失败", caught))
    if not ok3:
        fails.append("测试3：Skipped 被普通 except 吞掉")

    # ---------------- 测试 4：Aborted 也不被吞，且优先级高于跳过 ----------------
    ctrl3 = Control()
    eng3 = FakeEngine(ctrl3)
    ctrl3.request_stop()
    ctrl3.request_skip()
    got = None
    try:
        eng3.check_stop()
    except Aborted:
        got = "Aborted"
    except Skipped:
        got = "Skipped"
    except Exception:
        got = "swallowed"
    ok4 = got == "Aborted"
    print("测试4 中止优先于跳过：%s（%s）" % ("通过" if ok4 else "失败", got))
    if not ok4:
        fails.append("测试4：中止/跳过优先级不对")

    # ---------------- 测试 5：节流期间点跳过，提前结束且不消费信号 ----------------
    ctrl4 = Control()
    eng4 = FakeEngine(ctrl4)
    eng4.control = ctrl4
    # 模拟 engine.pace 的行为：跳过时提前返回但保留信号
    def pace(total):
        deadline = time.time() + total
        while True:
            if ctrl4.stop.is_set():
                raise Aborted()
            if ctrl4.skip.is_set():
                return
            if time.time() >= deadline:
                return
            time.sleep(0.2)
    threading.Thread(target=lambda: (time.sleep(0.5), ctrl4.request_skip()),
                     daemon=True).start()
    t0 = time.time()
    pace(30)
    dt = time.time() - t0
    ok5 = dt < 3.0 and ctrl4.skip.is_set()
    print("测试5 节流中点跳过：%s（耗时 %.2f 秒，信号保留=%s）"
          % ("通过" if ok5 else "失败", dt, ctrl4.skip.is_set()))
    if not ok5:
        fails.append("测试5：节流期间跳过没提前结束或信号被消费")

    print()
    if fails:
        print("❌ 有 %d 项未通过：" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("✅ 跳过此步 5 项验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
