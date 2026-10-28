# -*- coding: utf-8 -*-
"""platforms —— 各政府/司法公开平台的采集处理器。

一个平台一个模块，模块里只有这个站点的知识：
    credit_china.py  信用中国（信息公示 + 专项查询）
    shixin.py        失信被执行人（zxgk.court.gov.cn）
    ccgp.py          中国政府采购网
    mohurd.py        住房和城乡建设部
    plap.py          军队采购网
    gsxt.py          国家企业信用信息公示系统
    wenshu.py        中国裁判文书网
    cnca.py          全国认证认可信息公共服务平台

引擎（engine.py）只做编排：选平台 → 调 handler → 收截图。
"""
from __future__ import annotations

from platforms.base import PlatformHandler
from platforms.ccgp import CcggHandler
from platforms.cnca import CncaHandler
from platforms.credit_china import CreditChinaHandler
from platforms.gsxt import GsxtHandler
from platforms.mohurd import MohurdHandler
from platforms.plap import PlapHandler
from platforms.shixin import ShixinHandler
from platforms.wenshu import WenshuHandler

__all__ = [
    "PlatformHandler", "CcggHandler", "CncaHandler", "CreditChinaHandler",
    "GsxtHandler", "MohurdHandler", "PlapHandler", "ShixinHandler",
    "WenshuHandler", "HANDLER_CLASSES", "build_handlers",
]

#: 平台 key -> handler 类
HANDLER_CLASSES = {
    "credit_china": CreditChinaHandler,
    "shixin": ShixinHandler,
    "ccgp": CcggHandler,
    "mohurd": MohurdHandler,
    "plap": PlapHandler,
    "gsxt": GsxtHandler,
    "wenshu": WenshuHandler,
    "cnca": CncaHandler,
}


def build_handlers(engine) -> dict:
    """为引擎创建全部平台处理器。"""
    return {key: cls(engine) for key, cls in HANDLER_CLASSES.items()}
