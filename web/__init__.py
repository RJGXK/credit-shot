# -*- coding: utf-8 -*-
"""web —— 本地 Web 界面层。

分工：
    server.py   FastAPI 应用、路由挂载、静态资源
    api.py      REST 端点（启动/继续/跳过/中止/凭据/自检）
    events.py   事件总线：把引擎线程的日志与状态推给浏览器（SSE）
    models.py   请求/响应模型

引擎（engine.py）完全不知道 Web 的存在：它只调用 log 回调，
由本层把回调转成事件推给前端。
"""
from __future__ import annotations

__all__ = ["server", "api", "events", "models"]
