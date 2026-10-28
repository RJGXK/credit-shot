# -*- coding: utf-8 -*-
"""验证打包后的 exe 会弹出「软件窗口」（而不是跳浏览器）。

    python tools/verify_window.py

检查项：
  1. 启动 exe，等一会儿；
  2. 枚举顶层窗口，找标题为「企业信用一键截图工具」的**独立窗口**；
  3. 该窗口不能是浏览器窗口（浏览器的标题里带「用户配置 / Microsoft Edge」等）；
  4. 窗口截图，确认界面渲染正常；
  5. 关掉窗口后，进程与端口都应消失（不留后台孤儿）。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "企业信用截图工具", "企业信用截图工具.exe")
SHOT = os.path.join(ROOT, "dist", "_软件窗口.png")

APP_TITLE = "企业信用一键截图工具"
PASS, FAIL = [], []

user32 = ctypes.windll.user32


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("✔" if ok else "✘", name,
                       ("  —— " + detail) if detail else ""))


def list_windows():
    """列出所有可见且有标题的顶层窗口。"""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if not title:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append((hwnd, title, rect.left, rect.top,
                      rect.right, rect.bottom))
        return True

    user32.EnumWindows(cb, 0)
    return found


def find_app_window(timeout: float = 90.0):
    """找本程序的独立窗口（排除浏览器与资源管理器）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, title, l, t, r, b in list_windows():
            if title.strip() != APP_TITLE:
                continue
            if (r - l) < 400 or (b - t) < 300:
                continue
            return hwnd, title, (l, t, r, b)
        time.sleep(1.0)
    return None


def _dpi_scale():
    """本机显示缩放（物理像素 / 逻辑像素）。"""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi and dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def grab_window(hwnd):
    """抓取窗口内容（用 PrintWindow，不受其它窗口遮挡影响）。

    注意 DPI 虚拟化：
      GetWindowRect 在非 DPI 感知的进程里返回**逻辑坐标**，
      而 PrintWindow 抓到的是**物理像素**位图。
      直接拿逻辑坐标去裁物理位图，就会裁掉右边和底部。
      这里用 DwmGetWindowAttribute 取真实物理边界，取不到再按缩放换算。
    """
    from PIL import Image

    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi

    width = height = 0
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9：真实物理边界，不受虚拟化影响
    rect = wintypes.RECT()
    hr = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect),
                                   ctypes.sizeof(rect))
    if hr == 0 and rect.right > rect.left:
        left, top = rect.left, rect.top
        width, height = rect.right - rect.left, rect.bottom - rect.top
    else:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        left, top = rect.left, rect.top
        width, height = rect.right - rect.left, rect.bottom - rect.top
        # 逻辑坐标 → 物理坐标
        scale = _dpi_scale()
        if scale > 1.01:
            width = int(width * scale)
            height = int(height * scale)
            left = int(left * scale)
            top = int(top * scale)

    if width <= 0 or height <= 0:
        return None

    hdc = user32.GetWindowDC(hwnd)
    gdi = ctypes.windll.gdi32
    mem_dc = gdi.CreateCompatibleDC(hdc)
    bitmap = gdi.CreateCompatibleBitmap(hdc, width, height)
    gdi.SelectObject(mem_dc, bitmap)
    # PW_RENDERFULLCONTENT = 2：能抓到 WebView2 这类合成窗口的内容
    user32.PrintWindow(hwnd, mem_dc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height          # 负数 = 自上而下
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    buf = ctypes.create_string_buffer(width * height * 4)
    gdi.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(bmi), 0)
    img = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)

    gdi.DeleteObject(bitmap)
    gdi.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)
    return img


def main() -> int:
    if not os.path.isfile(EXE):
        print("找不到打包产物：%s" % EXE)
        print("请先运行：python tools/build_exe.py")
        return 1

    print("=== 启动 exe，等待软件窗口 ===")
    proc = subprocess.Popen([EXE])

    hit = find_app_window(timeout=90)
    check("弹出了独立的软件窗口", hit is not None,
          hit[2] and "位置 %s" % (hit[2],) if hit else "90 秒内未找到")
    if not hit:
        try:
            proc.kill()
        except Exception:
            pass
        return 1

    hwnd, title, rect = hit
    print("窗口标题：%s   位置：%s" % (title, rect))

    # 不是浏览器窗口
    browser_like = any(w in title for w in ("Edge", "Chrome", "用户配置", "Microsoft"))
    check("不是浏览器窗口", not browser_like, title)

    # 截图确认界面渲染（PrintWindow，不受遮挡影响）
    try:
        time.sleep(1.5)
        img = grab_window(hwnd)
        if img is None:
            check("窗口截图成功（界面已渲染）", False, "取不到窗口位图")
        else:
            img.save(SHOT)
            # 界面上应该有大片非背景色内容
            colors = img.convert("RGB").getcolors(maxcolors=1000000) or []
            distinct = len(colors)
            check("窗口截图成功（界面已渲染）",
                  img.width > 400 and img.height > 300 and distinct > 200,
                  "%d×%d，%d 种颜色 → %s" % (img.width, img.height, distinct, SHOT))
    except Exception as exc:
        check("窗口截图成功（界面已渲染）", False, str(exc))

    # 服务应该也在跑（窗口加载的就是它）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    alive = False
    for port in range(8760, 8840):
        try:
            with opener.open("http://127.0.0.1:%d/api/ping" % port,
                             timeout=1.0) as r:
                if b"credit-shot" in r.read():
                    alive = True
                    break
        except Exception:
            continue
    check("窗口背后的本地服务可用", alive)

    # 关窗口 → 进程应退出、端口应释放
    print("\n=== 关闭窗口，验证退出 ===")
    user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
    for _ in range(30):
        if proc.poll() is not None:
            break
        time.sleep(1)
    check("关闭窗口后进程自动退出", proc.poll() is not None,
          "退出码 %s" % proc.poll())
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass

    time.sleep(2)
    still = False
    for port in range(8760, 8840):
        try:
            with opener.open("http://127.0.0.1:%d/api/ping" % port,
                             timeout=0.8) as r:
                if b"credit-shot" in r.read():
                    still = True
                    break
        except Exception:
            continue
    check("关闭后端口已释放（不留后台孤儿）", not still)

    print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("   -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
