# -*- coding: utf-8 -*-
"""公开前的敏感信息终审：扫描远程 tarball 解出的真实内容。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 明确判定为「测试假数据」的样本，出现在这些值里不算泄漏
BENIGN = {
    "13800138000", "13800000000", "914403001922382216",
    "110101199001011234", "12345678901", "11111111111",
    "secret123", "Dummy-123456", "Dummy-Pass-9",
}

PATTERNS = [
    ("GitHub token", re.compile(r"(gho_|ghp_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("OpenAI 风格 key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("身份证号", re.compile(r"\b[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
]

# 密钥类赋值：右边像真值（排除占位/测试词）
ASSIGN = re.compile(
    r"(?i)\b(api_?key|secret|password|passwd|access_?token|app_?key|"
    r"client_?secret|private_?key)\b\s*[:=]\s*['\"]([^'\"]{4,})['\"]"
)
FAKE_WORDS = ("dummy", "fake", "wrong", "test", "example", "placeholder",
              "xxx", "***", "changeme", "your_", "sample", "demo", "<", "%s")

TEXT_EXT = (".py", ".md", ".txt", ".js", ".css", ".html", ".json", ".ini",
            ".vbs", ".bat", ".nsi", ".cfg", ".yaml", ".yml", ".toml", ".sh")


def is_texty(path):
    low = path.lower()
    if low.endswith(TEXT_EXT):
        return True
    # 无扩展名的小文件也当文本看
    try:
        if os.path.getsize(path) < 20000:
            with open(path, "rb") as fh:
                chunk = fh.read(4096)
            if b"\x00" not in chunk:
                return True
    except OSError:
        pass
    return False


def main():
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, ROOT)
            if not is_texty(p):
                continue
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
                txt = data.decode("utf-8", "replace")
            except OSError:
                continue
            scanned += 1
            for label, rx in PATTERNS:
                for m in rx.finditer(txt):
                    val = m.group(0)
                    if val in BENIGN or any(b in val for b in BENIGN):
                        continue
                    line = txt.count("\n", 0, m.start()) + 1
                    hits.append("%s:%d  [%s] %s" % (rel, line, label, val[:70]))
            for m in ASSIGN.finditer(txt):
                val = m.group(2)
                if val in BENIGN or any(b in val.lower() for b in FAKE_WORDS):
                    continue
                if len(val) < 8 or val.count("x") > 3:
                    continue
                line = txt.count("\n", 0, m.start()) + 1
                hits.append("%s:%d  [赋值] %s = %s" % (rel, line, m.group(1), val[:60]))

    print("扫描文本文件 %d 个" % scanned)
    if hits:
        print("\n❌ 命中 %d 处，需要人工确认：" % len(hits))
        for h in hits[:40]:
            print("   ", h)
        return 1
    print("✅ 未发现真实凭据 / 密钥 / 隐私数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
