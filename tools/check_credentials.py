# -*- coding: utf-8 -*-
"""凭据与打码服务专项自测。

覆盖三个曾经让功能「看起来不生效」的坑：
  1. 界面不回显密码 → 点「保存到本地」把磁盘上已有的密码清空
  2. 界面清空 API Key 输入框 → 点「保存到本地」把已保存的 Key 清空
  3. 运行时没把 captcha_key 传给引擎 → 打码服务全程不启用

测试前会备份真实凭据文件，测完原样恢复。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PORT = 8777
BASE = "http://127.0.0.1:%d" % PORT
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CRED = os.path.join(os.environ["APPDATA"], "企业信用截图工具", "凭据.ini")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("✔" if ok else "✘", name, ("  —— " + detail) if detail else ""))


def api(path, payload=None, timeout=40):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with OP.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_ini(path):
    import configparser
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    return {s: dict(cfg[s]) for s in cfg.sections()}


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not os.path.exists(CRED):
        print("（本机还没有凭据文件，跳过写入类测试）")
        return 0
    before = read_ini(CRED)
    backup = CRED + ".selftest_bak"
    shutil.copy2(CRED, backup)

    srv = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; sys.path.insert(0, %r);"
         "from web.server import serve;"
         "serve(host='127.0.0.1', port=%d, open_ui=False)" % (ROOT, PORT)],
        cwd=ROOT)
    try:
        for _ in range(60):
            try:
                with OP.open(BASE + "/api/ping", timeout=1) as r:
                    if b"credit-shot" in r.read():
                        break
            except Exception:
                time.sleep(1)

        # ---------- 1) 接口能读到「已保存」状态 ----------
        info = api("/api/credentials")
        has_pwd = [c["platform"] for c in info["credentials"] if c["has_password"]]
        check("接口返回 has_password / captcha_key_set",
              "captcha_key_set" in info,
              "captcha_key_set=%s" % info.get("captcha_key_set"))
        check("打码 Key 已被识别为已保存", bool(info.get("captcha_key_set")))

        # ---------- 2) 密码留空 = 不修改 ----------
        payload = {"credentials": [
            {"platform": c["platform"], "username": c["username"],
             "password": "", "enabled": c["enabled"]}
            for c in info["credentials"]],
            "captcha_key": ""}
        api("/api/credentials", payload)
        after = read_ini(CRED)
        same_pwd = all(
            after.get(c["platform"], {}).get("password", "")
            == before.get(c["platform"], {}).get("password", "")
            for c in info["credentials"])
        check("保存时密码留空 → 原有密码未被清空", same_pwd,
              "涉及平台 %s" % (has_pwd or "（当前无已存密码的平台）"))
        same_key = (after.get("__captcha__", {}).get("api_key", "")
                    == before.get("__captcha__", {}).get("api_key", ""))
        check("保存时 Key 留空 → 原有 Key 未被清空", same_key,
              "Key 长度 %d" % len(after.get("__captcha__", {}).get("api_key", "")))

        # ---------- 3) 空 Key 也能测打码服务（用已保存的）----------
        try:
            res = api("/api/captcha/test", {"api_key": ""})
            check("空 Key 点「测试打码服务」能测出余额（复用已保存的 Key）",
                  "balance" in res, "余额 %.2f 点" % res.get("balance", 0))
        except Exception as exc:
            check("空 Key 点「测试打码服务」能测出余额（复用已保存的 Key）",
                  False, str(exc)[:100])

        # ---------- 4) 运行时引擎能拿到 Key 与凭据 ----------
        # 直接走 TaskManager 的取值逻辑，不启动浏览器（采集任务会占用
        # Edge 的调试端口，把 Playwright 驱动挤掉）
        from web.api import TaskManager
        mgr = TaskManager()
        cap_key = mgr._load_captcha_key()
        cred_map = mgr._load_credentials_map()
        check("运行时能读到打码服务 API Key", bool(cap_key),
              "长度 %d" % len(cap_key))
        check("运行时能读到已配置的平台账号", bool(cred_map),
              "平台：%s" % "、".join(cred_map.keys()))
        # 引擎拿到 Key 后 CaptchaSolver 才算启用
        from core.captcha import CaptchaSolver
        solver = CaptchaSolver(cap_key, "cn", lambda s: None)
        check("CaptchaSolver 处于启用状态", solver.enabled)

        # ---------- 5) 前端：密码框/Key 框显示「已保存」提示 ----------
        with sync_playwright() as p:
            b = p.chromium.launch(
                executable_path=r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                args=["--remote-debugging-port=9408"])
            pg = b.new_page(viewport={"width": 1180, "height": 815})
            pg.goto(BASE + "/", wait_until="networkidle")
            pg.wait_for_timeout(1500)
            pg.click("#btnCredentials")
            pg.wait_for_timeout(1200)
            ph = pg.evaluate("""() => {
              const box = document.querySelector('#credRows');
              const rows = Array.from(box.querySelectorAll('.cred-row'));
              return {
                pw: rows.map(r => (r.querySelector('input[type=password]')||{}).placeholder),
                key: (document.querySelector('#captchaKey')||{}).placeholder,
                keyValue: (document.querySelector('#captchaKey')||{}).value
              };
            }""")
            b.close()

        saved_pw = [c for c in info["credentials"] if c["has_password"]]
        if saved_pw:
            check("密码框显示「已保存（留空则不修改）」",
                  any("已保存" in (x or "") for x in ph["pw"]),
                  str(ph["pw"])[:80])
        else:
            check("密码框提示正确（本机尚未保存任何密码，显示「密码」）",
                  all((x or "") == "密码" for x in ph["pw"]),
                  str(ph["pw"])[:80])
        check("API Key 框显示「已保存」且不回显明文",
              "已保存" in (ph["key"] or "") and not ph["keyValue"],
              "placeholder=%r value=%r" % (ph["key"], ph["keyValue"]))

        # ---------- 6) 单元级：临时文件上验证「留空 = 不修改」 ----------
        from auth.credentials import (Credential, load_credentials,
                                      save_credentials)
        tmp = os.path.join(tempfile.gettempdir(), "cs_cred_unit.ini")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            save_credentials([Credential(platform="wenshu",
                                         username="13800000000",
                                         password="secret123")], tmp)
            save_credentials([Credential(platform="wenshu",
                                         username="13800000000",
                                         password="",
                                         enabled=True)], tmp)
            got = load_credentials(tmp)
            check("单元级：空密码保存后原密码仍在",
                  bool(got) and got[0].password == "secret123",
                  "密码=%r" % (got[0].password if got else None))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
        return 0 if not FAIL else 1
    finally:
        try:
            shutil.copy2(backup, CRED)
            os.remove(backup)
            print("已恢复原始凭据文件")
        except Exception as exc:
            print("⚠ 恢复凭据文件失败：%s（备份在 %s）" % (exc, backup))
        try:
            srv.kill()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
