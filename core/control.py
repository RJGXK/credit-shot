# -*- coding: utf-8 -*-
"""控制信号：界面（现在是 Web 前端）与引擎之间的握手。

引擎跑在后台线程里，界面的四个按钮通过这里下指令：

    【我已处理，继续截图】 → request_resume()
    【跳过此步】           → request_skip()
    【中止】               → request_stop()

`waiting` 是引擎写给界面看的：表示「我现在卡住了，等人处理」，
界面据此把按钮高亮成可点击状态。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from core.errors import Aborted, Skipped

__all__ = ["Control"]


@dataclass
class Control:
    """界面与引擎之间的信号量。"""

    resume: threading.Event = field(default_factory=threading.Event)
    skip: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    waiting: threading.Event = field(default_factory=threading.Event)  # 引擎正在等人工处理

    def clear(self) -> None:
        self.resume.clear()
        self.skip.clear()

    def request_resume(self) -> None:
        self.skip.clear()
        self.resume.set()

    def request_skip(self) -> None:
        self.resume.clear()
        self.skip.set()

    def request_stop(self) -> None:
        self.stop.set()

    # ------------------------------------------------------------ 可中断等待
    def wait(self, seconds: float, tick: float = 0.2) -> None:
        """可被【中止】/【跳过此步】打断的等待。

        这是「跳过此步」能真正生效的关键：以前所有等待都用 ``time.sleep``，
        用户点按钮后引擎完全听不见，必须等整段等待跑完才有机会响应。
        这里改成小步轮询，**最迟 0.2 秒**就能把信号送到引擎。

        收到【中止】抛 Aborted（整轮收尾）；
        收到【跳过此步】抛 Skipped（只跳过当前这一步）。
        """
        deadline = time.time() + max(0.0, float(seconds))
        while True:
            if self.stop.is_set():
                raise Aborted()
            if self.skip.is_set():
                self.skip.clear()
                raise Skipped()
            left = deadline - time.time()
            if left <= 0:
                return
            time.sleep(min(tick, left))
