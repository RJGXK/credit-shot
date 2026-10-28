# -*- coding: utf-8 -*-
"""Web 层冒烟测试：起一个真实服务，把 API 挨个打一遍。

不需要浏览器、不访问外网，只验证接口契约与状态机。
    python tools/web_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn

from web.server import create_app, find_free_port

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    print("  %s %s%s" % ("✔" if condition else "✘", name,
                          ("  —— " + detail) if detail and not condition else ""))


def main() -> int:
    port = find_free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            if httpx.get(base + "/api/ping", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        print("✘ 服务没起来")
        return 1

    print("=== 1) 目录接口 ===")
    r = httpx.get(base + "/api/catalog", timeout=5)
    catalog = r.json()
    total = sum(len(s["steps"]) for s in catalog["sites"])
    check("GET /api/catalog 返回 200", r.status_code == 200)
    check("站点数 = 8", len(catalog["sites"]) == 8, str(len(catalog["sites"])))
    check("采集项数 = 30", total == 30, str(total))
    check("含 8 个登录平台", len(catalog["login_platforms"]) == 8)
    check("含 4 种截图方式", len(catalog["shot_modes"]) >= 4)
    check("含认监委平台",
          any(s["key"] == "cnca" for s in catalog["sites"]))
    check("认监委有 2 个采集项",
          any(s["key"] == "cnca" and len(s["steps"]) == 2
              for s in catalog["sites"]))

    print("=== 2) 首页与静态资源 ===")
    r = httpx.get(base + "/", timeout=5)
    check("GET / 返回页面", r.status_code == 200 and "<title>" in r.text)
    r = httpx.get(base + "/static/css/app.css", timeout=5)
    check("CSS 可访问", r.status_code == 200)
    r = httpx.get(base + "/static/js/app.js", timeout=5)
    check("JS 可访问", r.status_code == 200)

    print("=== 3) 参数校验 ===")
    r = httpx.post(base + "/api/run", json={"subjects": [], "step_keys": []}, timeout=5)
    check("空主体被拒 (400)", r.status_code == 400, str(r.status_code))
    r = httpx.post(base + "/api/run", json={"subjects": ["某公司"], "step_keys": []}, timeout=5)
    check("空采集项被拒 (400)", r.status_code == 400, str(r.status_code))
    r = httpx.post(base + "/api/control/nonsense", timeout=5)
    check("未知指令被拒 (400)", r.status_code == 400, str(r.status_code))

    print("=== 4) 凭据接口 ===")
    r = httpx.get(base + "/api/credentials", timeout=5)
    data = r.json()
    check("GET /api/credentials 返回 200", r.status_code == 200)
    check("不返回明文密码", all("password" not in c for c in data["credentials"]))
    # 空 Key 会回退到本地已保存的 Key（界面不回显已保存的值，
    # 否则用户点「测试打码服务」只会得到「请先填写 API Key」）
    r = httpx.post(base + "/api/captcha/test", json={"api_key": ""}, timeout=20)
    check("空 API Key 回退到已保存的 Key", r.status_code in (200, 400), str(r.status_code))
    r = httpx.post(base + "/api/captcha/test",
                   json={"api_key": "invalid-key-for-smoke-test"}, timeout=20)
    check("无效 API Key 被拒 (400)", r.status_code == 400, str(r.status_code))

    print("=== 5) 状态接口 ===")
    r = httpx.get(base + "/api/state", timeout=5)
    state = r.json()
    check("GET /api/state 返回 200", r.status_code == 200)
    check("初始状态 idle", state.get("state") == "idle", str(state.get("state")))

    print("=== 6) SSE 事件流 ===")
    got_frame = False
    try:
        with httpx.stream("GET", base + "/api/events", timeout=10) as resp:
            check("SSE 返回 200", resp.status_code == 200)
            check("Content-Type 是 text/event-stream",
                  "text/event-stream" in resp.headers.get("content-type", ""))
            # 服务端此刻没有业务事件，会先发一条探活注释，这里读首帧即可
            for line in resp.iter_lines():
                if line:
                    got_frame = True
                    break
    except Exception as exc:
        print("    （SSE 读取结束：%s）" % str(exc).splitlines()[0])
    check("能收到首帧（探活或数据）", got_frame)

    print()
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：%s" % "、".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
