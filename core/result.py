# -*- coding: utf-8 -*-
"""单个采集项的执行结果（纯数据）。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any

__all__ = ["StepResult"]


@dataclass
class StepResult:
    """一个采集项跑完之后的结论。

    ok=True  表示截图已生成（path 有值）；
    ok=False 表示被跳过或失败（message 里是原因）。
    """

    no: str
    key: str
    title: str
    company: str
    ok: bool
    path: str = ""
    message: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转成可 JSON 序列化的字典（Web 前端直接用）。"""
        return asdict(self)
