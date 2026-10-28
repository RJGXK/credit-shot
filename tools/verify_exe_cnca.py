# -*- coding: utf-8 -*-
"""验证**打包产物**跑出来的服务里，采集目录含 CNCA 的两个新采集项。

（源码里对了还不够 —— 打包漏模块的话，运行期才会炸。）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "企业信用截图工具")
EXE = os.path.join(DIST, "企业信用截图工具.exe")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(path, timeout=4.0):
    for port in range(8760, 8840):
        try:
            with _OPENER.open("http://127.0.0.1:%d%s" % (port, path),
                              timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception:
            continue
    return None, b""


def main():
    proc = None
    if http("/api/ping")[0] is None:
        print("启动打包产物…")
        proc = subprocess.Popen([EXE], cwd=DIST)
        for _ in range(40):
            time.sleep(1)
            if http("/api/ping")[0] is not None:
                break
    try:
        code, body = http("/api/catalog")
        if code != 200:
            print("✘ /api/catalog 返回 %s" % code)
            return 1
        cat = json.loads(body.decode("utf-8"))
        sites = cat.get("sites") or []
        # 采集项挂在每个站点的 steps 下（web_smoke.py 同款口径）
        steps = [st for s in sites for st in (s.get("steps") or [])]
        print("站点数 = %d" % len(sites))
        print("采集项数 = %d" % len(steps))
        print("登录平台数 = %d" % len(cat.get("login_platforms") or []))
        cnca = [s for s in steps if str(s.get("key", "")).startswith("cnca")]
        print("CNCA 采集项 = %d" % len(cnca))
        for s in cnca:
            print("   [%s] %s / %s" % (s.get("no"), s.get("title"), s.get("short")))

        ok = (len(sites) == 8 and len(steps) == 30 and len(cnca) == 2
              and len(cat.get("login_platforms") or []) == 8)
        print("\n%s" % ("✔ 打包产物目录正确（含 CNCA 两个采集项）"
                        if ok else "✘ 打包产物目录不对"))
        return 0 if ok else 1
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
