# -*- coding: utf-8 -*-
"""REST 端点 + 任务管理。

前端只需要这些接口：

    GET  /api/catalog              站点/采集项目录与默认参数
    GET  /api/state                当前运行状态
    POST /api/run                  启动一轮任务
    POST /api/control/{action}     继续 / 跳过 / 中止
    GET  /api/events               SSE：日志、状态、结果实时推送
    GET  /api/credentials          读取本地凭据（密码脱敏）
    POST /api/credentials          保存凭据到本地
    POST /api/credentials/load     从本地载入并回显（脱敏）
    POST /api/captcha/test         测试打码服务
    POST /api/selfcheck            功能自检
    POST /api/open-output          用系统文件管理器打开输出目录
    POST /api/validate-output      校验输出目录是否可用
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from auth.credentials import (Credential, credentials_to_map,
                              default_cred_path, load_captcha_key,
                              load_credentials, mask_username,
                              save_captcha_key, save_credentials)
from config import (BROWSER_CHANNELS, DEFAULTS, INFO_BAR_MODES, MODE_FORMAT,
                    MODE_HINT, MODE_OF_LABEL, SITES, step_supports)
from core.control import Control
from core.result import StepResult
from engine import Engine
from web.events import (EVENT_DONE, EVENT_LOG, EVENT_RESULT, EVENT_STATUS,
                        EventBus)
from web.models import (CaptchaKeyPayload, CredentialItem, CredentialPayload,
                         RunRequest)

router = APIRouter()

# 状态机：idle -> running -> (waiting) -> idle
STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_WAITING = "waiting"
STATE_DONE = "done"


class TaskManager:
    """管理当前这一轮任务：引擎、线程、控制信号、事件总线。

    引擎跑在自己的后台线程里（Playwright 是同步 API，不能在事件循环里跑），
    界面通过 control 发指令、通过事件总线收日志。
    """

    def __init__(self) -> None:
        self.bus = EventBus()
        self.control = Control()
        self.engine: Optional[Engine] = None
        self.thread: Optional[threading.Thread] = None
        self.state = STATE_IDLE
        self.results: List[StepResult] = []
        self.last_error = ""
        self._lock = threading.Lock()
        self._watcher: Optional[threading.Thread] = None

    # ------------------------------------------------------------ 状态
    def set_state(self, state: str, detail: str = "") -> None:
        with self._lock:
            self.state = state
        self.bus.publish(EVENT_STATUS, {"state": state, "detail": detail})

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "waiting": self.control.waiting.is_set(),
                "results": [r.to_dict() for r in self.results],
                "error": self.last_error,
            }

    # ------------------------------------------------------------ 运行
    def start(self, request: RunRequest) -> None:
        if self.is_running():
            raise HTTPException(status_code=409, detail="已有任务在运行")

        opts = request.options
        subjects = [s.strip() for s in request.subjects if s.strip()]
        step_keys = [k for k in request.step_keys if k]
        if not subjects:
            raise HTTPException(status_code=400, detail="请先填写查询主体")
        if not step_keys:
            raise HTTPException(status_code=400, detail="请至少选择一个采集项")

        output_dir = (opts.output_dir or DEFAULTS["output_dir"]).strip()
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="输出目录不可用：%s" % exc)

        self.bus.clear()
        self.results = []
        self.last_error = ""
        self.control = Control()
        self.set_state(STATE_RUNNING)

        creds = self._load_credentials_map()
        captcha_key = self._load_captcha_key()
        # 打码服务是否可用要在日志里说清楚：没配 Key 时所有验证码都会回落人工，
        # 否则用户只看到「一直在等人工」，不知道是没配还是没生效。
        self._log("打码服务：%s"
                  % ("已启用（API Key 已配置）" if captcha_key
                     else "未配置 API Key —— 图形验证码将全部转人工处理"))
        if creds:
            self._log("已加载 %d 个平台账号：%s"
                      % (len(creds), "、".join(creds.keys())))
        engine = Engine(
            output_dir=output_dir,
            browser=opts.browser if opts.browser in BROWSER_CHANNELS else "Edge",
            shot_mode=opts.shot_mode,
            subject_mode=MODE_OF_LABEL.get(opts.subject_mode, "company"),
            pace_seconds=opts.pace_seconds,
            make_pdf=opts.make_pdf,
            timeout=DEFAULTS.get("timeout", 60),
            manual_timeout=DEFAULTS.get("manual_timeout", 900),
            credentials=creds,
            captcha_key=captcha_key,
            log=self._log,
            control=self.control,
        )
        self.engine = engine
        self.thread = threading.Thread(
            target=self._run, args=(engine, subjects, step_keys), daemon=True)
        self.thread.start()
        self._start_watcher()

    def _run(self, engine: Engine, subjects: List[str], step_keys: List[str]) -> None:
        try:
            results = engine.run(subjects, step_keys)
            with self._lock:
                self.results = results
            for r in results:
                self.bus.publish(EVENT_RESULT, r.to_dict())
        except Exception as exc:
            self.last_error = str(exc)
            self._log("✘ 任务异常：%s" % exc)
        finally:
            self.set_state(STATE_DONE)
            self.bus.publish(EVENT_DONE, {"count": len(self.results)})
            self.engine = None

    def _log(self, message: str) -> None:
        """引擎线程的日志出口：转成事件推给前端。"""
        self.bus.publish(EVENT_LOG, message)

    def _start_watcher(self) -> None:
        """监控「引擎是否在等人工处理」，变化时推状态给前端。"""
        def watch():
            last = False
            while True:
                if self.thread is None or not self.thread.is_alive():
                    return
                waiting = self.control.waiting.is_set()
                if waiting != last:
                    last = waiting
                    if waiting:
                        self.set_state(STATE_WAITING, "等待人工处理")
                    elif self.state == STATE_WAITING:
                        self.set_state(STATE_RUNNING)
                time.sleep(0.3)

        self._watcher = threading.Thread(target=watch, daemon=True)
        self._watcher.start()

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ------------------------------------------------------------ 控制指令
    def control_action(self, action: str) -> Dict[str, Any]:
        if action == "resume":
            self.control.request_resume()
            self._log("→ 收到【我已处理，继续截图】")
        elif action == "skip":
            self.control.request_skip()
            self._log("→ 收到【跳过此步】")
        elif action == "stop":
            self.control.request_stop()
            self._log("→ 收到【中止】")
        else:
            raise HTTPException(status_code=400, detail="未知指令：%s" % action)
        return {"ok": True, "action": action}

    # ------------------------------------------------------------ 凭据
    def _load_credentials_map(self) -> Dict[str, Dict[str, str]]:
        try:
            # include_incomplete=True：把「已启用但密码为空」的也带出去，
            # 引擎才能在日志里说清是缺账号还是缺密码。
            return credentials_to_map(load_credentials(default_cred_path()),
                                      include_incomplete=True)
        except Exception:
            return {}

    def _load_captcha_key(self) -> str:
        """读本地打码服务 API Key（明文只在内存里，绝不进日志）。"""
        try:
            return (load_captcha_key(default_cred_path()) or "").strip()
        except Exception:
            return ""

    def _captcha_key(self) -> str:
        try:
            return load_captcha_key(default_cred_path())
        except Exception:
            return ""


# 全局单例：整个进程只跑一个任务
manager = TaskManager()


# ==================================================================== 目录
@router.get("/api/catalog")
def get_catalog() -> Dict[str, Any]:
    """站点/采集项目录 + 默认参数（前端启动时拉一次）。"""
    from config import LOGIN_PLATFORMS

    sites = []
    for site in SITES:
        steps = []
        for st in site["steps"]:
            steps.append({
                "no": st["no"],
                "mark": st.get("mark", ""),
                "key": st["key"],
                "title": st["title"],
                "short": st.get("short", st["title"]),
                "subject": st.get("subject", "company"),
            })
        sites.append({
            "key": site["key"],
            "name": site["name"],
            "short": site.get("short", site["name"]),
            "platform": site.get("platform", site["name"]),
            "platform_url": site.get("platform_url", ""),
            "steps": steps,
        })
    return {
        "sites": sites,
        "defaults": {
            "output_dir": DEFAULTS["output_dir"],
            "browser": DEFAULTS["browser"],
            "shot_mode": DEFAULTS["shot_mode"],
            "subject_mode": DEFAULTS["subject_mode"],
            "pace_seconds": DEFAULTS["pace_seconds"],
            "make_pdf": DEFAULTS["make_pdf"],
        },
        "shot_modes": list(INFO_BAR_MODES) + ["原图", "原图+日期弹窗"],
        "browsers": list(BROWSER_CHANNELS.keys()),
        "mode_format": MODE_FORMAT,
        "mode_hint": MODE_HINT,
        "login_platforms": [
            {"key": p["key"], "name": p["name"], "account": p.get("account", ""),
             "hint": p.get("hint", "")}
            for p in LOGIN_PLATFORMS
        ],
    }


@router.get("/api/state")
def get_state() -> Dict[str, Any]:
    return manager.snapshot()


# ==================================================================== 任务
@router.post("/api/run")
def start_run(request: RunRequest) -> Dict[str, Any]:
    manager.start(request)
    return {"ok": True}


@router.post("/api/control/{action}")
def control(action: str) -> Dict[str, Any]:
    return manager.control_action(action)


@router.get("/api/events")
async def events() -> StreamingResponse:
    """SSE：把事件总线里的消息实时推给浏览器。"""
    async def stream():
        # 先补发历史（前端刷新/断线重连后不至于丢日志）
        for event in manager.bus.history():
            yield _sse(event)
        async for event in manager.bus.aiter_events():
            if event is None:
                yield ": keep-alive\n\n"     # 探活注释，避免连接被中间层掐断
                continue
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(event: Dict[str, Any]) -> str:
    import json
    body = json.dumps({"kind": event.get("kind"), "data": event.get("data"),
                        "seq": event.get("seq")}, ensure_ascii=False)
    return "data: %s\n\n" % body


@router.post("/api/selfcheck")
def selfcheck() -> Dict[str, Any]:
    """功能自检（会启动浏览器，耗时几十秒）。"""
    if manager.is_running():
        raise HTTPException(status_code=409, detail="任务运行中，不能自检")
    lines: List[str] = []

    def collect(msg: str) -> None:
        lines.append(msg)
        manager.bus.publish(EVENT_LOG, msg)

    engine = Engine(output_dir=DEFAULTS["output_dir"], browser=DEFAULTS["browser"],
                    log=collect)
    ok = engine.self_check()
    return {"ok": ok, "lines": lines}


# ==================================================================== 凭据
@router.get("/api/credentials")
def get_credentials() -> Dict[str, Any]:
    """读取本地凭据。**密码不返回**，只返回是否已配置。"""
    path = default_cred_path()
    creds = load_credentials(path)
    items = []
    for c in creds:
        items.append({
            "platform": c.platform,
            "platform_name": c.platform_name,
            "username": c.username,
            "username_masked": mask_username(c.username),
            "has_password": bool(c.password),
            "enabled": c.enabled,
        })
    return {
        "path": path,
        "credentials": items,
        "captcha_key_set": bool(load_captcha_key(path)),
    }


@router.post("/api/credentials")
def save_credential(payload: CredentialPayload) -> Dict[str, Any]:
    """把凭据与打码 Key 保存到本地文件。"""
    path = default_cred_path()
    creds = [Credential(platform=item.platform, username=item.username,
                        password=item.password, enabled=item.enabled)
             for item in payload.credentials]
    ok = save_credentials(creds, path)
    ok2 = save_captcha_key(payload.captcha_key, path)
    if not (ok and ok2):
        raise HTTPException(status_code=500, detail="保存失败")
    return {"ok": True, "path": path}


@router.post("/api/credentials/load")
def load_credential() -> Dict[str, Any]:
    """从本地载入（脱敏回显）。"""
    return get_credentials()


@router.post("/api/captcha/test")
def test_captcha(payload: CaptchaKeyPayload) -> Dict[str, Any]:
    """调打码服务查余额，验证 API Key 是否可用。

    api_key 传空 → 用本地已保存的 Key 测试（输入框不回显已保存的值，
    否则用户点「测试」只会得到「请先填写 API Key」）。
    """
    key = (payload.api_key or "").strip()
    if not key:
        try:
            key = (load_captcha_key(default_cred_path()) or "").strip()
        except Exception:
            key = ""
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    from core.yescaptcha import CaptchaError, YesCaptcha

    try:
        balance = YesCaptcha(key, "cn").get_balance()
    except CaptchaError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="测试失败：%s" % exc)
    return {"ok": True, "balance": balance}


# ==================================================================== 目录
@router.post("/api/validate-output")
def validate_output(payload: Dict[str, str]) -> Dict[str, Any]:
    path = (payload or {}).get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="路径为空")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="目录不可用：%s" % exc)
    return {"ok": True, "path": os.path.abspath(path)}


@router.post("/api/open-in-browser")
def open_in_browser() -> Dict[str, Any]:
    """用系统默认浏览器打开界面。

    界面默认跑在软件窗口里（pywebview），这个接口是给用户一个
    「改用浏览器打开」的备选入口，比如想在另一块屏幕上用浏览器看。
    """
    host = "127.0.0.1"
    port = 8760
    # 找到实际监听的端口（服务可能因为端口占用而顺延）
    for p in range(8760, 8840):
        import socket
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                port = p
                break
    url = "http://%s:%d/" % (host, port)
    try:
        import desktop_window
        ok = desktop_window.open_in_external_browser(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="打开失败：%s" % exc)
    if not ok:
        raise HTTPException(status_code=400, detail="无法调用系统浏览器")
    return {"ok": True, "url": url}


@router.post("/api/open-output")
def open_output(payload: Dict[str, str]) -> Dict[str, Any]:
    """用系统文件管理器打开输出目录。"""
    path = (payload or {}).get("path", "").strip() or DEFAULTS["output_dir"]
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(os.path.abspath(path))   # noqa: S606  (Windows 专用)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="打开失败：%s" % exc)
    return {"ok": True, "path": os.path.abspath(path)}
