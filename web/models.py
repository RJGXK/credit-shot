# -*- coding: utf-8 -*-
"""Web 层的请求/响应模型。

用 Pydantic 表达，作用有三个：
  1. 前端传错字段时立刻返回 422，不至于把脏数据带进引擎；
  2. 文档自动生成（/docs）；
  3. 类型明确，读代码时不用猜字段含义。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

__all__ = [
    "RunRequest", "CredentialItem", "CredentialPayload", "CaptchaKeyPayload",
    "BrowseRequest", "RunOptions",
]


class RunOptions(BaseModel):
    """一次任务的可选参数。"""

    output_dir: str = Field("", description="截图保存目录")
    browser: str = Field("Edge", description="浏览器：Edge / Chrome")
    shot_mode: str = Field("原图+日期弹窗+信息条", description="截图方式")
    subject_mode: str = Field("单位", description="查询类型：单位 / 人员")
    pace_seconds: int = Field(30, ge=0, le=600, description="节流间隔（秒）")
    make_pdf: bool = Field(False, description="是否额外生成 PDF 汇总")


class RunRequest(BaseModel):
    """启动一轮采集任务。"""

    subjects: List[str] = Field(default_factory=list, description="查询主体，每行一个")
    step_keys: List[str] = Field(default_factory=list, description="要采集的采集项 key")
    options: RunOptions = Field(default_factory=RunOptions)


class CredentialItem(BaseModel):
    """一个平台的账号凭据。"""

    platform: str = Field(..., description="平台 key")
    username: str = Field("", description="账号")
    password: str = Field("", description="密码")
    enabled: bool = Field(True, description="是否参与自动登录")


class CredentialPayload(BaseModel):
    """保存凭据与打码 Key。"""

    credentials: List[CredentialItem] = Field(default_factory=list)
    captcha_key: str = Field("", description="打码服务 API Key")


class CaptchaKeyPayload(BaseModel):
    """只测打码服务。"""

    api_key: str = Field(..., description="打码服务 API Key")


class BrowseRequest(BaseModel):
    """把某个路径作为输出目录（前端目录选择器的回传）。"""

    path: str = Field(..., description="目录绝对路径")
