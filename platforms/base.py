# -*- coding: utf-8 -*-
"""平台采集处理器的公共基类。

设计约定
--------
* 一个平台 = 一个 handler 类 = 一个模块，模块里只放「这个站点怎么查」的知识；
* 通用能力（浏览器、页面动作、截图、验证码）在 core 包里，handler 直接调用；
* handler 通过 `self.engine` 访问编排层（节流、等待人工、截图落盘、登录）；
* `collect_*` 是采集入口，`collect_group` 是「同组采集项一次进站点」的入口。
"""
from __future__ import annotations

from typing import List

from core.page import wait_ready as _wait_ready
from core.result import StepResult

__all__ = ["PlatformHandler", "STEP_ENTRY_BY_KIND", "GROUP_BY_KEY"]


class PlatformHandler:
    """平台采集处理器基类。"""

    #: 平台标识（与 config.LOGIN_PLATFORMS 里的 key 对应）
    key: str = ""
    #: 平台中文名
    title: str = ""

    def __init__(self, engine):
        self.engine = engine

    # ---- 编排层能力的便捷代理（平台代码里写起来更短）----
    @property
    def log(self):
        return self.engine.log

    @property
    def control(self):
        return self.engine.control

    @property
    def timeout(self) -> int:
        return self.engine.timeout

    @property
    def output_dir(self) -> str:
        return self.engine.output_dir

    @property
    def subject(self):
        """当前查询主体（单位/人员信息）。"""
        return self.engine.current_subject

    # ---- 生命周期钩子 ----
    def reset_subject_state(self) -> None:
        """切换到下一个查询主体时清理本平台的会话状态。"""

    # ---- 页面等待（自动带上「用户中止」的感知）----
    def wait_ready(self, page, js: str, timeout: int = 30,
                   interval: float = 1.0) -> bool:
        """轮询等待页面就绪；用户点了【中止】会立即抛异常。"""
        return _wait_ready(page, js, timeout, interval,
                           should_stop=self.engine.check_stop)

    # ---- 采集入口（子类按需实现）----
    def collect_group(self, page, company: str, gsteps: List[dict],
                      results: List[StepResult], shots: List[str]) -> None:
        """一组采集项共用一次「进入站点」的场景。"""
        for step in gsteps:
            self.engine.run_one(page, company, step, results, shots)


#: 单个采集项（kind）-> handler 上的入口方法名
STEP_ENTRY_BY_KIND = {
    "creditchina": "collect_list",
    "creditchina_person": "collect_person_list",
    "zxgk": "collect_dishonest",
    "ccgp": "collect",
    "gsxt_basic": "collect_basic",
    "gsxt_section": "collect_section",
    "gsxt_blacklist": "collect_blacklist",
}

#: 共享会话分组（group）-> handler 上的入口方法名
GROUP_BY_KEY = {
    "mohurd": "collect_group",
    "plap": "collect_group",
    "gsxt_detail": "collect_group",
    "ws": "collect_group",
    "ws_xinghui": "collect_group",
    "cnca": "collect_group",
}
