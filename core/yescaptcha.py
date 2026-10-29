# -*- coding: utf-8 -*-
"""验证码识别服务客户端（YesCaptcha）。

官方文档：https://docs.yescaptcha.com/zh/getting-started/quickstart/

接口
----
  POST {base}/createTask     {"clientKey":…, "task":{…}}
      · **同步**题型（图片识别类）直接返回 solution，无需再查
      · **异步**题型只返回 taskId
  POST {base}/getTaskResult  {"clientKey":…, "taskId":…}
      -> {"errorId":0, "status":"processing"|"ready", "solution":{…}}
  POST {base}/getBalance     {"clientKey":…}  -> {"errorId":0, "balance":…}

节点：国际 https://api.yescaptcha.com ／ 国内 https://cn.yescaptcha.com
      两者互为备份，某个节点连不上会自动切到另一个。

题型（来自官方 /data/task-types.json）：
  同步  ImageToTextTaskOcrBase  图片英数字识别（2 点）
  同步  ImageToTextTaskMuggle   同上（2 点）
  异步  ImageToTextTask         图片识别（4 点）
  异步  NoCaptchaTaskProxyless  reCAPTCHA v2
  异步  HCaptchaTaskProxyless   hCaptcha
  异步  TurnstileTaskProxyless  Cloudflare Turnstile
  ⚠ 官方题型里**没有** GeeTest / 极验滑块，天艾点选也没有 ——
    这类滑块仍需人工完成。

为什么自己写而不用官方 SDK：
  工具的依赖被刻意控制在 `playwright / pillow / pywin32` 三个，
  这里用标准库 urllib 实现，不引入任何新依赖。

安全：API Key 只从本地凭据文件/界面传入，绝不写进日志。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional

__all__ = ["YesCaptcha", "CaptchaError", "API_BASE_CN", "API_BASE_INTL"]

API_BASE_CN = "https://cn.yescaptcha.com"
API_BASE_INTL = "https://api.yescaptcha.com"

# 常见错误码 -> 中文提示
ERR_TEXT = {
    "ERROR_KEY_DOES_NOT_EXIST": "API Key 不存在",
    "ERROR_ZERO_BALANCE": "账户余额为 0",
    "ERROR_NO_SLOT_AVAILABLE": "并发超限（同一时间任务太多）",
    "ERROR_TASK_NOT_SUPPORTED": "不支持的任务类型",
    "ERROR_TASK_PROPERTY_EMPTY": "缺少必要参数",
    "ERROR_NO_SUCH_CAPCHA_ID": "任务 ID 不存在",
    "ERROR_IP_NOT_ALLOWED": "IP 未加入白名单",
    "ERROR_BAD_TOKEN": "Token 无效",
    "ERROR_BAD_PARAMETERS": "参数不正确",
    "ERROR_IMAGE_UNREADABLE": "图片无法识别",
}


class CaptchaError(Exception):
    """打码服务调用失败。"""


class YesCaptcha:
    """YesCaptcha 客户端。api_key 为空时不发请求（调用方应先判断）。"""

    def __init__(self, api_key: str, region: str = "cn",
                 log: Optional[Callable[[str], None]] = None,
                 timeout: int = 40, poll_interval: float = 5.0):
        self.api_key = (api_key or "").strip()
        self.region = region if region in ("cn", "intl") else "cn"
        self.log = log or (lambda s: None)
        self.timeout = int(timeout)
        self.poll_interval = float(poll_interval)
        # 按优先级排的节点列表（首选 + 备份）
        self.bases: List[str] = ([API_BASE_CN, API_BASE_INTL] if self.region == "cn"
                                 else [API_BASE_INTL, API_BASE_CN])
        self._base = self.bases[0]
        self._last_node_error = ""

    # ------------------------------------------------------------ 底层
    def _post(self, path: str, payload: dict) -> dict:
        if not self.api_key:
            raise CaptchaError("未配置 API Key")
        body = json.dumps(payload).encode("utf-8")
        last_exc = None
        for base in self.bases:
            req = urllib.request.Request(
                base + path, data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                # 4xx/5xx 是服务端错误，换节点也没用，直接报错
                raise CaptchaError("HTTP %s（%s）"
                                   % (exc.code, base))
            except Exception as exc:
                last_exc = exc
                self._last_node_error = "%s：%s" % (base, exc)
                continue            # 网络不通 -> 换备用节点
            try:
                obj = json.loads(raw)
            except Exception:
                raise CaptchaError("返回内容不是 JSON：%s" % raw[:120])
            if int(obj.get("errorId") or 0) != 0:
                code = obj.get("errorCode") or ""
                desc = obj.get("errorDescription") or ""
                msg = ERR_TEXT.get(code, code or desc or "未知错误")
                raise CaptchaError("%s（%s）" % (msg, code or desc))
            self._base = base
            return obj
        raise CaptchaError("打码服务连接失败（%s）" % (last_exc or "未知错误"))

    def create_task(self, task: dict) -> dict:
        """创建任务。**同步**题型直接带 solution 返回；异步题型只给 taskId。"""
        return self._post("/createTask", {"clientKey": self.api_key, "task": task})

    def get_result(self, task_id: str) -> dict:
        return self._post("/getTaskResult", {"clientKey": self.api_key, "taskId": task_id})

    def get_balance(self) -> float:
        obj = self._post("/getBalance", {"clientKey": self.api_key})
        try:
            return float(obj.get("balance") or 0)
        except Exception:
            return 0.0

    def _solve(self, task: dict, sol_key: str, max_wait: float = 150.0) -> str:
        """创建任务并取结果（同步/异步都支持）。"""
        obj = self.create_task(task)
        sol = obj.get("solution") or {}
        if sol.get(sol_key):
            return str(sol[sol_key])
        task_id = obj.get("taskId")
        if not task_id:
            # 有些异步接口直接返回 status=ready 但 solution 结构不同
            if obj.get("status") == "ready":
                raise CaptchaError("识别结果为空")
            raise CaptchaError("createTask 没有返回 taskId")
        # 异步：每 5 秒查一次，最多 120 次 / 5 分钟
        deadline = time.time() + max_wait
        tries = 0
        while tries < 120 and time.time() < deadline:
            tries += 1
            r = self.get_result(task_id)
            status = r.get("status")
            if status == "ready":
                sol = r.get("solution") or {}
                if sol.get(sol_key):
                    return str(sol[sol_key])
                raise CaptchaError("识别结果为空")
            if status == "processing":
                time.sleep(self.poll_interval)
                continue
            raise CaptchaError("未知状态：%s" % status)
        raise CaptchaError("等待识别结果超时")

    # ------------------------------------------------------------ 题型
    def solve_image_to_text(self, image_bytes: bytes) -> str:
        """识别图形验证码（图片里的英数字），返回文本。

        先用**异步题型 ImageToTextTask**（官方标注「识别率更高」），实测也确实更准：

        信用中国的验证码是 95x25 的小图，字符带**描边阴影**，
        同步题型（ImageToTextTaskOcrBase）会把描边当成第二个字符 ——
        真值 "C6A1" 被读成 "C6A11"，提交必然被判错；
        异步题型同一张图读成 "C6A1"（真值）/ "Q9H0"（真值），明显更准。

        异步题型报错或返回空时，再回落到同步题型（便宜一半）。
        """
        body = base64.b64encode(image_bytes).decode("ascii")
        try:
            text = self._solve({"type": "ImageToTextTask", "body": body,
                                "numeric": 4, "case": 0}, "text")
            text = (text or "").strip()
            if text:
                return text
        except CaptchaError as exc:
            self._last_node_error = "异步题型失败：%s" % exc
        body = base64.b64encode(image_bytes).decode("ascii")
        return (self._solve({"type": "ImageToTextTaskOcrBase", "body": body},
                             "text") or "").strip()

    def solve_image_to_text_async(self, image_bytes: bytes, numeric: int = 4,
                                  case_sensitive: bool = False) -> str:
        """图片识别的异步题型（识别率更高但更贵，4 点）。"""
        body = base64.b64encode(image_bytes).decode("ascii")
        task = {"type": "ImageToTextTask", "body": body,
                "numeric": int(numeric), "case": bool(case_sensitive)}
        return (self._solve(task, "text") or "").strip()

    def solve_recaptcha_v2(self, site_key: str, page_url: str,
                           invisible: bool = False) -> str:
        """识别 reCAPTCHA v2，返回 gRecaptchaResponse token。"""
        task = {"type": "NoCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
                "isInvisible": bool(invisible)}
        return self._solve(task, "gRecaptchaResponse")

    def solve_hcaptcha(self, site_key: str, page_url: str) -> str:
        """识别 hCaptcha，返回 gRecaptchaResponse token。"""
        task = {"type": "HCaptchaTaskProxyless",
                "websiteURL": page_url, "websiteKey": site_key}
        return self._solve(task, "gRecaptchaResponse")

    def solve_turnstile(self, site_key: str, page_url: str) -> str:
        """识别 Cloudflare Turnstile，返回 token。"""
        task = {"type": "TurnstileTaskProxyless",
                "websiteURL": page_url, "websiteKey": site_key}
        return self._solve(task, "token")

    # ------------------------------------------------------------ 便捷
    def solve_captcha_image_element(self, element, timeout: int = 20) -> str:
        """给一个 Playwright 的 <img> 元素截图并识别。"""
        try:
            import io
            from PIL import Image
            shot = element.screenshot(timeout=timeout * 1000)
            img = Image.open(io.BytesIO(shot)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return self.solve_image_to_text(buf.getvalue())
        except CaptchaError:
            raise
        except Exception as exc:
            raise CaptchaError("截图失败：%s" % exc)
