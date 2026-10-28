# -*- coding: utf-8 -*-
"""把文件上传为 GitHub Release 附件，**精确指定资产名**。

为什么不用 `gh release upload`：
gh 走 GraphQL 上传时同样会被服务端改写资产名。

**GitHub 服务端会剥离资产名里的非 ASCII 字符**（实测 2026-10-28）：
    企业信用一键截图工具_安装包.exe -> _.exe
    使用说明.md                        -> default.md
    界面预览.png                       -> default.png
    Preview-界面预览.png               -> Preview-.png
即：**中文资产名在 GitHub Release 上不可用**，必须用纯 ASCII 名
（ASCII 前缀能完整保留，中文段会被整段删掉）。
另外服务端不允许同名资产，重复上传同一降级名会返回 422。

用法：
    python tools/upload_release_assets.py <tag> <本地文件> [资产名 ...]
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

UPLOAD_TMPL = ("https://uploads.github.com/repos/{owner}/{repo}/"
                "releases/{rid}/assets?name={name}")


def gh_json(args):
    out = subprocess.check_output(["gh"] + args)
    return json.loads(out.decode("utf-8"))


def upload(rid, owner, repo, token, path, asset_name):
    name_q = urllib.parse.quote(asset_name, safe="")
    url = UPLOAD_TMPL.format(owner=owner, repo=repo, rid=rid, name=name_q)
    size = os.path.getsize(path)
    print("上传 %s → %s (%.1f MB)" % (path, asset_name, size / 1048576.0))
    with open(path, "rb") as fh:
        req = urllib.request.Request(url, data=fh, method="POST")
        req.add_header("Authorization", "token %s" % token)
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Content-Length", str(size))
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=3600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    print("   ✔ id=%s  name=%s  size=%s  state=%s"
          % (data.get("id"), data.get("name"), data.get("size"),
             data.get("state")))
    return data


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tag = sys.argv[1]
    items = []
    rest = sys.argv[2:]
    while rest:
        p = rest.pop(0)
        name = rest.pop(0) if rest else os.path.basename(p)
        items.append((p, name))

    token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()
    rel = gh_json(["api", "repos/{owner}/{repo}/releases/tags/%s" % tag])
    rid = rel["id"]
    owner, repo = rel["url"].split("/releases/")[0].split("/")[-2:]
    print("release id=%s  repo=%s/%s" % (rid, owner, repo))

    for path, name in items:
        if not os.path.isfile(path):
            print("跳过（不存在）: %s" % path)
            continue
        upload(rid, owner, repo, token, path, name)

    print("\n最终资产：")
    for a in gh_json(["api", "repos/%s/%s/releases/tags/%s" % (owner, repo, tag)])["assets"]:
        print("  · %-46s %10d bytes  %s" % (a["name"], a["size"],
                                             a["browser_download_url"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
