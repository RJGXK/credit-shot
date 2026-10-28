# -*- coding: utf-8 -*-
"""事件总线：把后台引擎线程的消息推给浏览器。

引擎跑在后台线程里，它的 log 回调会把每一行日志塞进这里；
Web 层用 SSE（Server-Sent Events）把队列里的消息实时吐给前端。

为什么不用 WebSocket：
  * 这里只有「服务端 -> 浏览器」一个方向的单播，SSE 足够；
  * SSE 自带断线重连，浏览器刷新或网络抖动都能自动续上；
  * 不需要额外依赖（FastAPI 已内置）。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Iterator, List, Optional

__all__ = ["EventBus", "EVENT_LOG", "EVENT_STATUS", "EVENT_RESULT", "EVENT_DONE"]


EVENT_LOG = "log"        # 一行运行日志
EVENT_STATUS = "status"  # 状态变化（空闲/运行中/等待人工/已结束）
EVENT_RESULT = "result"  # 单个采集项的结果
EVENT_DONE = "done"      # 整轮任务结束


class EventBus:
    """线程安全的事件队列。

    引擎线程调用 publish()，FastAPI 的 SSE 生成器调用 iter_events()。
    """

    def __init__(self, maxlen: int = 2000):
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._condition = threading.Condition(self._lock)
        self._seq = 0
        self._closed = False

    # ------------------------------------------------------------ 生产者
    def publish(self, kind: str, data: Any = None) -> None:
        """发布一个事件（可从任意线程调用）。"""
        with self._condition:
            self._seq += 1
            event = {"seq": self._seq, "kind": kind, "data": data,
                     "ts": time.time()}
            self._events.append(event)
            self._history.append(event)
            self._condition.notify_all()

    def close(self) -> None:
        """标记总线关闭，SSE 循环会收到 None 后结束。"""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def clear(self) -> None:
        """清空历史（新一轮任务开始时调用）。"""
        with self._condition:
            self._events = []
            self._history.clear()
            self._seq = 0

    # ------------------------------------------------------------ 消费者
    def history(self) -> List[Dict[str, Any]]:
        """当前保留的历史事件（前端重连时补发）。"""
        with self._lock:
            return list(self._history)

    def iter_events(self, timeout: float = 1.0) -> Iterator[Optional[Dict[str, Any]]]:
        """逐个产出事件。

        * 正常事件 -> dict
        * 等待超时 -> None（供 SSE 探活，保持连接不因空闲被掐断）
        * 总线关闭 -> {"kind": "__closed__"}，随后迭代结束
        """
        while True:
            with self._condition:
                if self._events:
                    event = self._events.pop(0)
                elif self._closed:
                    event = {"kind": "__closed__"}
                else:
                    event = None
                    self._condition.wait(timeout)
            if event is None:
                yield None
                continue
            yield event
            if event.get("kind") == "__closed__":
                return

    # ------------------------------------------------------------ 异步适配
    async def aiter_events(self, timeout: float = 1.0):
        """FastAPI 用的异步版本：把阻塞等待交给线程池，不卡住事件循环。"""
        loop = asyncio.get_running_loop()
        iterator = self.iter_events(timeout)
        while True:
            event = await loop.run_in_executor(None, next, iterator, None)
            if event is None:
                yield None
                continue
            yield event
            if event.get("kind") == "__closed__":
                return
