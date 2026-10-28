# -*- coding: utf-8 -*-
"""auth —— 账号凭据与自动登录。

* ``credentials``  凭据的数据模型、本地文件读写、账号脱敏
* ``autologin``    按平台的自动登录流程（填表、提交、结果判定、验证码挂起）

安全约定：密码只进内存和本机文件，日志一律脱敏。
"""
from __future__ import annotations

__all__ = ["credentials", "autologin"]
