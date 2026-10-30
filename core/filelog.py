# -*- coding: utf-8 -*-
"""运行日志落盘：把每一行运行日志写到本地文件，关软件不丢。

需求背景（用户反馈）：
    「日志一关闭就不存在了」—— 之前日志只推给界面（SSE），窗口一关
    就全没了，出问题想回查没有任何凭据。

设计：
  * 写到 %APPDATA%\\企业信用截图工具\\logs\\运行日志_YYYYMMDD.log，
    与凭据同一目录规则（源码版 / 安装版一致，用户好找）；
  * **按天分文件**，每天一个；超过 30 天的自动清理（防无限膨胀）；
  * 每行带时间戳；文件头记录程序版本（回查时知道当时是哪个版本跑的）；
  * 线程安全（引擎跑在后台线程）；写失败静默忽略 —— 日志落盘**绝不能**
    影响截图主流程。

用法：
    from core.filelog import FileLogger
    flog = FileLogger()          # 模块级单例：get_file_logger()
    flog.write("✔ 已保存：xxx.png")
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Optional

__all__ = ["FileLogger", "get_file_logger", "log_dir"]

_LOG_DIRNAME = "logs"
_MAX_AGE_DAYS = 30          # 超过 30 天的日志自动删除
_LOCK = threading.Lock()
_INSTANCE: Optional["FileLogger"] = None

# 安全清洗：文件名里不允许出现的字符（Windows）
_SAFE_RE = re.compile(r'[\\/:*?"<>|\r\n]+')


def log_dir() -> str:
    """日志目录：``%APPDATA%\\企业信用截图工具\\logs``。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "企业信用截图工具", _LOG_DIRNAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.join(os.path.expanduser("~"), _LOG_DIRNAME)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    return d


def _app_version() -> str:
    """读程序版本号（读不到就返回未知）。"""
    try:
        import config
        return str(getattr(config, "APP_VERSION", "") or "未知版本")
    except Exception:
        return "未知版本"


class FileLogger:
    """把运行日志追加写进按天分文件的本地日志。线程安全。"""

    def __init__(self, directory: str = ""):
        self._dir = directory or log_dir()
        self._day = ""           # 当前写的是哪一天（YYYYMMDD）
        self._fh = None          # 打开的文件句柄（按天换文件）
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 核心
    def write(self, message: str) -> None:
        """追加一行日志。任何失败都静默忽略（不干扰主流程）。"""
        if not message:
            return
        try:
            with self._lock:
                day = time.strftime("%Y%m%d")
                if day != self._day or self._fh is None:
                    self._open(day)
                if self._fh is None:
                    return
                self._fh.write("%s  %s\n"
                               % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
                self._fh.flush()
        except Exception:
            pass

    def _open(self, day: str) -> None:
        """打开（或切换到）当天的日志文件，写文件头。

        文件头规则：当天**第一次**写时写大头部；同一天里**每次新会话**（软件重启）
        都补一行「新会话 + 当前版本」——之前只在文件头写一次版本，用户升级后
        当天日志头还是旧版本号（如 2.1.3），回查时完全被误导。
        """
        try:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
            path = os.path.join(self._dir, "运行日志_%s.log" % day)
            head = not os.path.exists(path)
            self._fh = open(path, "a", encoding="utf-8")
            self._day = day
            if head:
                self._fh.write("=" * 60 + "\n")
                self._fh.write("企业信用一键截图工具  运行日志  %s\n"
                               % time.strftime("%Y-%m-%d %H:%M:%S"))
                self._fh.write("程序版本：%s\n" % _app_version())
                self._fh.write("=" * 60 + "\n")
            else:
                self._fh.write("─" * 60 + "\n")
                self._fh.write("── 新会话开始  %s  程序版本：%s\n"
                               % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                  _app_version()))
        except Exception:
            self._fh = None

    def path(self) -> str:
        """当前日志文件完整路径。"""
        return os.path.join(self._dir, "运行日志_%s.log"
                            % (self._day or time.strftime("%Y%m%d")))

    def close(self) -> None:
        with self._lock:
            try:
                if self._fh is not None:
                    self._fh.close()
            except Exception:
                pass
            self._fh = None

    # ------------------------------------------------------------ 清理
    def cleanup(self, keep_days: int = _MAX_AGE_DAYS) -> int:
        """删除超过 keep_days 天的旧日志，返回删除个数。"""
        n = 0
        try:
            now = time.time()
            for name in os.listdir(self._dir):
                m = re.match(r"运行日志_(\d{8})\.log$", name)
                if not m:
                    continue
                try:
                    ts = time.mktime(time.strptime(m.group(1), "%Y%m%d"))
                except ValueError:
                    continue
                if now - ts > keep_days * 86400:
                    try:
                        os.remove(os.path.join(self._dir, name))
                        n += 1
                    except OSError:
                        pass
        except Exception:
            pass
        return n


def get_file_logger() -> FileLogger:
    """模块级单例（整个进程共用一个文件句柄）。"""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = FileLogger()
            # 进程启动时顺手清一次旧日志（放在锁里做，避免并发重复删）
            _INSTANCE.cleanup()
        return _INSTANCE

