# -*- coding: utf-8 -*-
"""自动登录链路实测：用临时假密码跑一次裁判文书网登录，确认链路是否走通。

只验证「引擎读到凭据 → 调 try_login → 提交 → 给出明确结果」这条链路，
不追求登录成功（假密码必然失败），要的是**明确的失败原因**而不是静默跳过。

测试前备份凭据文件，测完原样恢复。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PORT = 8779
BASE = "http://127.0.0.1:%d" % PORT
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CRED = os.path.join(os.environ["APPDATA"], "企业信用截图工具", "凭据.ini")
BACKUP = CRED + ".login_bak"
WAIT = float(os.environ.get("LOGIN_WAIT", "170"))


def api(path, payload=None, timeout=40):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with OP.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    backup_done = False
    if os.path.exists(CRED):
        shutil.copy2(CRED, BACKUP)
        backup_done = True

    # 临时写入假密码（真实的那个由用户在界面上填）
    try:
        from auth.credentials import (Credential, load_credentials,
                                      save_credentials)
        path = CRED
        creds = load_credentials(path)
        patched = []
        for c in creds:
            patched.append(Credential(platform=c.platform, username=c.username,
                                      password="WrongPass-ForLinkTest",
                                      enabled=c.enabled))
        if not patched:
            patched = [Credential(platform="wenshu",
                                  username="13800000000",
                                  password="WrongPass-ForLinkTest")]
        save_credentials(patched, path)
    except Exception as exc:
        print("准备临时凭据失败：%s" % exc)
        return 1

    srv = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; sys.path.insert(0, %r);"
         "from web.server import serve;"
         "serve(host='127.0.0.1', port=%d, open_ui=False)" % (ROOT, PORT)],
        cwd=ROOT)
    logs = []

    def listen():
        try:
            with OP.open(BASE + "/api/events", timeout=WAIT + 30) as r:
                for raw in r:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    # 事件结构：{"seq":…, "kind":"log", "data":"文本"}
                    if ev.get("kind") == "log":
                        t = ev.get("data") or ""
                        if t:
                            logs.append(str(t))
        except Exception:
            pass

    try:
        for _ in range(60):
            try:
                with OP.open(BASE + "/api/ping", timeout=1) as r:
                    if b"credit-shot" in r.read():
                        break
            except Exception:
                time.sleep(1)

        threading.Thread(target=listen, daemon=True).start()
        time.sleep(1.5)
        out = os.path.join(tempfile.gettempdir(), "cs_login_test")
        api("/api/run", {"subjects": ["华为技术有限公司"],
                         "step_keys": ["ws_susong"],
                         "options": {"output_dir": out, "browser": "Edge",
                                     "pace_seconds": 0, "timeout": 60,
                                     "shot_mode": "原图"}})
        print("已下发裁判文书网采集，等待登录流程…")

        deadline = time.time() + WAIT
        while time.time() < deadline:
            time.sleep(3)
            # 只等**结论性**日志：
            # 「使用已配置的账号自动登录」只是开场，不能据此判定
            if any(("自动登录成功" in t) or ("自动登录失败" in t)
                   or ("自动登录未完成" in t) or ("未自动登录" in t)
                   for t in logs):
                break
        time.sleep(2)

        print("\n=== 与登录相关的日志 ===")
        hit = False
        for t in logs:
            if any(k in t for k in ("登录", "凭据", "账号", "密码", "打码")):
                print("  ", t[:150])
                hit = True
        if not hit:
            print("   （没有捕获到登录相关日志）")
        print("\n=== 全部日志（末 12 条）===")
        for t in logs[-12:]:
            print("  ", t[:140])

        reached = any("使用已配置的账号自动登录" in t for t in logs)
        explicit = any(("自动登录失败" in t) or ("自动登录未完成" in t)
                       or ("自动登录成功" in t) or ("未自动登录" in t) for t in logs)
        print("\n%s 引擎取到了凭据并进入自动登录" % ("✔" if reached else "✘"))
        print("%s 自动登录给出了明确结果（不是静默跳过）" % ("✔" if explicit else "✘"))
        return 0 if (reached and explicit) else 1
    finally:
        try:
            api("/api/control/stop", {})
        except Exception:
            pass
        try:
            srv.kill()
        except Exception:
            pass
        if backup_done:
            try:
                shutil.copy2(BACKUP, CRED)
                os.remove(BACKUP)
                print("已恢复原始凭据文件")
            except Exception as exc:
                print("⚠ 恢复失败：%s（备份在 %s）" % (exc, BACKUP))


if __name__ == "__main__":
    sys.exit(main())
