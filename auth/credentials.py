# -*- coding: utf-8 -*-
"""账号凭据：数据模型、本地文件读写、账号脱敏。

为什么单独一个模块：
  1. 密码是敏感数据，必须有**唯一**的出入口，方便审计「密码会不会被打印到日志」；
  2. 界面（tkinter）与引擎（Playwright 线程）都要用到，这里是纯数据层，
     不依赖任何 GUI 库，线程安全。

安全约定
--------
- 密码只存在内存里（Engine 的 credentials 字典），进程退出即消失；
- 「保存到本地」是用户主动行为，写的是**明文 ini**，文件名固定为 `凭据.ini`，
  只保存在程序所在目录，不上传、不外发；
- **任何日志输出都必须走 mask_username()**，绝不能打印密码原文。
"""
from __future__ import annotations

import configparser
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import LOGIN_PLATFORMS

__all__ = [
    "Credential", "CRED_FILE_NAME", "default_cred_path", "load_credentials",
    "save_credentials", "mask_username", "credentials_to_map",
    "platform_by_key", "platform_by_host", "PLATFORM_BY_KEY",
]

# 本地凭据文件名（固定，放在程序目录）
CRED_FILE_NAME = "凭据.ini"

# 平台 key -> 平台定义
PLATFORM_BY_KEY = {p["key"]: p for p in LOGIN_PLATFORMS}


@dataclass
class Credential:
    """一条平台凭据。"""

    platform: str                       # LOGIN_PLATFORMS 里的 key
    username: str = ""
    password: str = ""
    enabled: bool = True
    note: str = ""

    @property
    def usable(self) -> bool:
        """是否可用：已启用且账号密码都填了。"""
        return bool(self.enabled and self.username.strip() and self.password)

    @property
    def platform_name(self) -> str:
        p = PLATFORM_BY_KEY.get(self.platform)
        return p["name"] if p else self.platform


def platform_by_key(key: str) -> Optional[dict]:
    return PLATFORM_BY_KEY.get(key)


def platform_by_host(host: str) -> Optional[dict]:
    """按域名找平台（用于把检测到的登录页归到某个平台）。"""
    if not host:
        return None
    host = host.lower().split(":")[0]
    for p in LOGIN_PLATFORMS:
        hosts = [h.lower() for h in (p.get("host", ""), p.get("login_host", ""))
                 if h]
        for h in hosts:
            if host == h or host.endswith("." + h) or h.endswith("." + host):
                return p
    return None


# ------------------------------------------------------------------ 脱敏
def mask_username(username: str) -> str:
    """账号脱敏：13800138000 -> 138****8000（保留前 3 后 4）。"""
    u = (username or "").strip()
    if not u:
        return ""
    n = len(u)
    if n <= 4:
        return u[0] + "*" * (n - 1)
    if n < 8:
        return u[:2] + "*" * (n - 3) + u[-1]
    return u[:3] + "****" + u[-4:]


# ------------------------------------------------------------------ 本地文件
def app_data_dir() -> str:
    """程序可写的用户数据目录。

    **统一放在 %APPDATA%\\企业信用截图工具\\**，源码版与安装版一致。

    为什么不用程序所在目录：
      * 打包成 exe 后，程序目录是 PyInstaller 的 _MEIPASS 临时解包目录，
        既是临时目录又可能没有写权限，配置放那儿会「退出即丢」；
      * 源码版和安装版如果各用各的目录，在一边填的账号密码在另一边看不到，
        表现为「明明保存了却不生效」。

    源码模式以前把凭据写在程序目录，老文件会自动搬过来（见 _migrate_legacy_cred）。
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "企业信用截图工具")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.expanduser("~")
    return d


def _migrate_legacy_cred(target: str) -> None:
    """源码版的老凭据文件（程序目录下的 凭据.ini）搬到统一位置。

    只在目标不存在时搬，且**不删源文件** —— 迁移出错也不会丢用户数据。
    """
    try:
        if os.path.exists(target):
            return
        legacy = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            CRED_FILE_NAME)
        if os.path.abspath(legacy) == os.path.abspath(target):
            return
        if os.path.isfile(legacy):
            shutil.copy2(legacy, target)
    except Exception:
        pass


def default_cred_path() -> str:
    """默认凭据文件路径。"""
    p = os.path.join(app_data_dir(), CRED_FILE_NAME)
    _migrate_legacy_cred(p)
    return p


def _cfg() -> configparser.RawConfigParser:
    # RawConfigParser：不做 % 插值，密码里带 % 号也不会报错
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str          # 保留 key 大小写
    return cfg


def load_credentials(path: Optional[str] = None) -> List[Credential]:
    """读本地凭据文件；文件不存在或损坏时返回空列表（不抛异常）。"""
    p = path or default_cred_path()
    out: List[Credential] = []
    try:
        if not os.path.exists(p):
            return out
        cfg = _cfg()
        cfg.read(p, encoding="utf-8")
        for key in cfg.sections():
            if key == CAPTCHA_SECTION:
                continue
            sec = cfg[key]
            out.append(Credential(
                platform=key,
                username=sec.get("username", "") or "",
                password=sec.get("password", "") or "",
                enabled=str(sec.get("enabled", "1")).strip() not in ("0", "false", "False", ""),
                note=sec.get("note", "") or "",
            ))
    except Exception:
        return []
    return out


def save_credentials(creds: List[Credential], path: Optional[str] = None) -> bool:
    """写本地凭据文件（明文）。成功返回 True。

    **密码留空 = 不修改**（保留磁盘上原有的密码）。
    界面出于安全不回显密码，如果把空值原样写回，用户每点一次「保存到本地」
    就会把已保存的密码清空，自动登录随之失效。
    """
    p = path or default_cred_path()
    try:
        cfg = _cfg()
        # 先把旧密码读出来：留空时用它兜底
        old_pwd: Dict[str, str] = {}
        try:
            if os.path.exists(p):
                old_cfg = _cfg()
                old_cfg.read(p, encoding="utf-8")
                for key in old_cfg.sections():
                    if key == CAPTCHA_SECTION:
                        # 打码 Key 段原样保留：本函数只管账号，
                        # 不然重写文件会把 Key 一起抹掉。
                        cfg[CAPTCHA_SECTION] = dict(old_cfg[key])
                        continue
                    old_pwd[key] = old_cfg[key].get("password", "") or ""
        except Exception:
            old_pwd = {}
        for c in creds:
            if not c.username and not c.password:
                continue
            pwd = c.password or ""
            if not pwd:
                pwd = old_pwd.get(c.platform, "")    # 留空 = 保持原样
            # section 名必须用 platform key，load 时才能对回引擎用的键；
            # 中文平台名另存一份只给人看。
            cfg[c.platform] = {
                "platform_name": PLATFORM_BY_KEY.get(c.platform, {}).get("name", c.platform),
                "username": c.username,
                "password": pwd,
                "enabled": "1" if c.enabled else "0",
                "note": c.note or "",
            }
        d = os.path.dirname(os.path.abspath(p))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 企业信用一键截图工具 —— 本地账号凭据\n")
            f.write("# 明文保存，仅限本机使用；请勿共享或上传。\n")
            f.write("# 删除本文件即可清除全部账号密码。\n")
            cfg.write(f)
        return True
    except Exception:
        return False


def credentials_to_map(creds: List[Credential],
                       include_incomplete: bool = False
                       ) -> Dict[str, Dict[str, str]]:
    """转成引擎要用的字典：{platform_key: {"username":…, "password":…}}。

    默认只包含「已启用且填全了」的凭据。
    include_incomplete=True 时，连「已启用但密码为空」的也一并带出去 ——
    这样引擎能明确告诉用户**缺的是账号还是密码**，而不是静默跳过自动登录。
    """
    out: Dict[str, Dict[str, str]] = {}
    for c in creds:
        if not c.enabled:
            continue
        if not include_incomplete and not c.usable:
            continue
        out[c.platform] = {"username": c.username, "password": c.password}
    return out


# ------------------------------------------------------------------ 打码服务 Key
CAPTCHA_SECTION = "__captcha__"


def load_captcha_key(path: Optional[str] = None) -> str:
    """从本地凭据文件里读打码服务 API Key。"""
    p = path or default_cred_path()
    try:
        if not os.path.exists(p):
            return ""
        cfg = _cfg()
        cfg.read(p, encoding="utf-8")
        if CAPTCHA_SECTION in cfg:
            return (cfg[CAPTCHA_SECTION].get("api_key", "") or "").strip()
    except Exception:
        return ""
    return ""


def save_captcha_key(api_key: str, path: Optional[str] = None) -> bool:
    """把打码服务 API Key 写进本地凭据文件（明文）。

    **Key 留空 = 不修改**（保留磁盘上原有的 Key）。
    界面上的 Key 输入框不回显已保存的值（也不该回显），
    空值原样写回会把 Key 清掉，打码服务随之失效。
    """
    p = path or default_cred_path()
    try:
        cfg = _cfg()
        if os.path.exists(p):
            cfg.read(p, encoding="utf-8")
        key = (api_key or "").strip()
        if not key:
            # 留空 = 保留原 Key；原来就没有就写一个空值（保持结构完整）
            key = (cfg[CAPTCHA_SECTION].get("api_key", "") or "").strip() \
                if CAPTCHA_SECTION in cfg else ""
        cfg[CAPTCHA_SECTION] = {"api_key": key}
        d = os.path.dirname(os.path.abspath(p))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 企业信用一键截图工具 —— 本地账号凭据\n")
            f.write("# 明文保存，仅限本机使用；请勿共享或上传。\n")
            f.write("# 删除本文件即可清除全部账号密码。\n")
            cfg.write(f)
        return True
    except Exception:
        return False
