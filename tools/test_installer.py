# -*- coding: utf-8 -*-
"""安装版实测：静默安装 → 启动软件窗口 → 验证界面 → 卸载 → 清理。

    python tools/test_installer.py

与普通服务测试不同，这里验证的是**用户真正看到的**：
  1. 静默安装成功、文件齐备；
  2. 从安装目录启动后，弹出的是**独立软件窗口**（不是浏览器）；
  3. 窗口里界面完整渲染（颜色数量判断不是白板）；
  4. 关掉窗口，进程自动退出、端口释放；
  5. 卸载干净，安装目录与桌面快捷方式都没了。
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
INSTALLER = os.path.join(ROOT, "dist", "企业信用一键截图工具_安装包.exe")
TEST_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                        "CreditShotTest")
APP_TITLE = "企业信用一键截图工具"

PASS, FAIL = [], []
user32 = ctypes.windll.user32


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("✔" if ok else "✘", name,
                       ("  —— " + detail) if detail else ""))


def list_windows():
    """所有可见且有标题的顶层窗口。"""
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
        if buf.value:
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


def find_app_window(timeout: float = 90.0):
    """找本程序的独立窗口（标题精确匹配，天然排除浏览器）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, title in list_windows():
            if title.strip() == APP_TITLE:
                return hwnd, title
        time.sleep(1.0)
    return None, ""


def grab_window(hwnd):
    """抓窗口内容（DwmGetWindowAttribute 取真实物理边界，避开 DPI 虚拟化）。"""
    from PIL import Image

    dwm = ctypes.windll.dwmapi
    rect = wintypes.RECT()
    hr = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect),
                                   ctypes.sizeof(rect))
    if hr != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    hdc = user32.GetWindowDC(hwnd)
    gdi = ctypes.windll.gdi32
    mem_dc = gdi.CreateCompatibleDC(hdc)
    bitmap = gdi.CreateCompatibleBitmap(hdc, width, height)
    gdi.SelectObject(mem_dc, bitmap)
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
    bmi.bmiHeader.biHeight = -height
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
    if not os.path.isfile(INSTALLER):
        print("找不到安装包：%s" % INSTALLER)
        print("请先运行：python tools/build_installer.py")
        return 1

    # 先清掉**本应用自己**上次测试留下的桌面快捷方式残留：
    # 不清的话，最后一步「桌面快捷方式已清理」分不清「卸载器没删」
    # 还是「上一轮的旧文件」，检查就不确定性了。（只删本应用自己的 lnk，安全）
    _desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    _stale_lnk = os.path.join(_desktop, APP_TITLE + ".lnk")
    if os.path.isfile(_stale_lnk):
        try:
            os.remove(_stale_lnk)
            print("（已清理上次残留的桌面快捷方式：%s）" % _stale_lnk)
        except OSError:
            pass

    print("=== 1) 静默安装 ===")
    print("安装包：%s（%.1f MB）"
          % (INSTALLER, os.path.getsize(INSTALLER) / 1024 / 1024))
    # /D 必须是最后一个参数，路径用反斜杠、不加引号
    r = subprocess.run([INSTALLER, "/S", "/D=" + TEST_DIR])
    check("安装程序退出码为 0", r.returncode == 0, "退出码 %d" % r.returncode)

    for _ in range(30):
        if os.path.isdir(TEST_DIR) and os.path.isfile(
                os.path.join(TEST_DIR, "企业信用截图工具.exe")):
            break
        time.sleep(2)

    check("安装目录已创建", os.path.isdir(TEST_DIR), TEST_DIR)
    exe = os.path.join(TEST_DIR, "企业信用截图工具.exe")
    check("主程序已安装", os.path.isfile(exe))
    check("运行时目录已安装", os.path.isdir(os.path.join(TEST_DIR, "_internal")))
    check("使用说明已安装", os.path.isfile(os.path.join(TEST_DIR, "使用说明.md")))
    check("卸载程序已安装",
          os.path.isfile(os.path.join(TEST_DIR, "uninstall.exe")))

    print("\n=== 2) 从安装目录启动，验证软件窗口 ===")
    proc = subprocess.Popen([exe])

    hwnd, title = find_app_window(timeout=90)
    check("弹出了独立的软件窗口", bool(hwnd), title or "90 秒内未找到窗口")
    if not hwnd:
        try:
            proc.kill()
        except Exception:
            pass
        return 1

    check("窗口标题正确", title.strip() == APP_TITLE, title)

    # 界面是否真的渲染出来了（颜色数量 > 200 说明不是白板）
    shot = os.path.join(ROOT, "dist", "_安装版窗口.png")
    try:
        time.sleep(2)
        img = grab_window(hwnd)
        if img is None:
            check("窗口内界面已渲染", False, "取不到窗口位图")
        else:
            img.save(shot)
            colors = len(img.convert("RGB").getcolors(maxcolors=1000000) or [])
            check("窗口内界面已渲染", colors > 200,
                  "%d×%d，%d 种颜色 → %s" % (img.width, img.height, colors, shot))
    except Exception as exc:
        check("窗口内界面已渲染", False, str(exc))

    # 背后的本地服务可用
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    alive = False
    for port in range(8760, 8840):
        try:
            with opener.open("http://127.0.0.1:%d/api/ping" % port,
                             timeout=1.0) as resp:
                if b"credit-shot" in resp.read():
                    alive = True
                    break
        except Exception:
            continue
    check("窗口背后的本地服务可用", alive)

    print("\n=== 3) 关窗，验证退出 ===")
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
                             timeout=0.8) as resp:
                if b"credit-shot" in resp.read():
                    still = True
                    break
        except Exception:
            continue
    check("关闭后端口已释放（不留后台孤儿）", not still)

    print("\n=== 4) 卸载 ===")
    uninst = os.path.join(TEST_DIR, "uninstall.exe")
    if os.path.isfile(uninst):
        r2 = subprocess.run([uninst, "/S"])
        check("卸载程序退出码为 0", r2.returncode == 0,
              "退出码 %d" % r2.returncode)
        for _ in range(25):
            if not os.path.isdir(TEST_DIR):
                break
            time.sleep(2)
        check("安装目录已清理", not os.path.isdir(TEST_DIR),
              "仍存在" if os.path.isdir(TEST_DIR) else "")
    else:
        check("卸载程序存在", False)

    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    lnk = os.path.join(desktop, "企业信用一键截图工具.lnk")
    # 卸载器静默模式是「复制自身到 %TEMP% 再执行」：目录删完到 lnk 删除
    # 之间有先后顺序，给最多 10 秒宽限，避免检查跑在卸载器前面。
    for _ in range(10):
        if not os.path.isfile(lnk):
            break
        time.sleep(1)
    check("桌面快捷方式已清理", not os.path.isfile(lnk))

    print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("   -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
