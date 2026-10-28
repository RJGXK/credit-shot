# -*- coding: utf-8 -*-
"""core —— 与业务无关的基础设施层。

分层约定（自下而上）：

    core.subject    纯数据：查询主体的解析与判定
    core.result     纯数据：单个采集项的结果
    core.control    纯数据：界面与引擎之间的控制信号
    core.errors     异常体系：控制流用异常，业务错误用 EngineError
    core.browser    浏览器生命周期（Edge/Chrome + CDP 接管）
    core.page       页面动作原语（填值 / 点击 / 等待）
    core.capture    截图与合成（信息条 / Windows 日期面板）
    core.captcha    验证码识别客户端（YesCaptcha 兼容接口）

这一层不包含任何「某个站点怎么查」的知识，
那些知识一律放在 platforms 包里。
"""
from __future__ import annotations

__all__ = [
    "errors", "subject", "result", "control",
]
