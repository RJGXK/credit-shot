# -*- coding: utf-8 -*-
"""异常体系。

区分两类异常，用途完全不同：

* **控制流异常**（Aborted / Skipped）：用户在界面上点了【中止】/【跳过此步】，
  引擎要立刻停下来或跳过当前步骤。这是正常交互，不是错误。
* **业务异常**（EngineError 及其子类）：站点结构变了、元素找不到、超时等。
  统一继承 EngineError，调用方可以只捕获 EngineError 兜住所有可预期的失败，
  而真正的程序缺陷（TypeError 之类）仍然会往上抛，不会被误吞。

**为什么 Aborted / Skipped 继承 BaseException 而不是 Exception**
----------------------------------------------------------
这两个是「控制流信号」，不是错误。平台上到处是 ``except Exception:`` 的兜底
（等页面、点按钮、填输入框），一旦跳过信号被它们吞掉，用户点的【跳过此步】
就会变成「静默失败」—— 程序继续跑，用户完全不知道跳过了。
继承 BaseException 之后，任何 ``except Exception`` 都抓不住它们，
信号必然一路冒泡到引擎的调度层被正确处理。
（这和标准库的 KeyboardInterrupt / SystemExit 同一思路。）
"""
from __future__ import annotations

__all__ = [
    "Aborted", "Skipped", "EngineError", "PageError", "LoginError",
]


class Aborted(BaseException):
    """用户点了【中止】：整轮任务立刻收尾。"""


class Skipped(BaseException):
    """用户点了【跳过此步】：只跳过当前这一步，继续下一步。"""


class EngineError(Exception):
    """引擎可预期的失败基类。

    凡是「站点改版 / 元素找不到 / 超时」这类问题都应抛这个，
    由编排层统一记录成一条失败结果，而不是让整个任务崩掉。
    """


class PageError(EngineError):
    """页面操作失败：元素找不到、点击不生效、等待超时等。"""


class LoginError(EngineError):
    """自动登录失败：账号密码错误、验证码没过、登录窗没出来等。"""
