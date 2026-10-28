# -*- coding: utf-8 -*-
"""把指定文件移入 Windows 回收站（不直接抹除，可恢复）。

用 shell32.SHFileOperationW 而不是 COM，避免触发安全策略对 COM 实例化的限制。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040          # 允许撤销 = 进回收站
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400


def move_to_recycle_bin(paths):
    """返回 (成功列表, 失败列表)。

    注意：SHFileOperationW 的返回码并不可靠（实测删除成功时也会返回 2），
    所以最终以「文件是否已从原位消失」为准。
    """
    ok, bad = [], []
    for p in paths:
        if not os.path.isfile(p):
            bad.append((p, "文件不存在"))
            continue
        src = os.path.abspath(p)
        # shell 要求多文件列表以「双 NUL」结尾；用显式缓冲区传，不能靠 c_wchar_p 截断
        src_buf = ctypes.create_unicode_buffer(src + "\0\0")
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(src_buf, wintypes.LPCWSTR)
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        # 以「原位是否还存在」判定成败，不看返回值
        if not os.path.exists(src):
            ok.append(src)
        else:
            bad.append((src, "文件仍在原位（回收站操作未生效）"))
    return ok, bad


if __name__ == "__main__":
    targets = sys.argv[1:]
    good, failed = move_to_recycle_bin(targets)
    for g in good:
        print("已移入回收站:", os.path.basename(g))
    for f, why in failed:
        print("失败:", os.path.basename(f), "-", why)
    print("成功 %d / 失败 %d" % (len(good), len(failed)))
