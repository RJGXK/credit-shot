# -*- coding: utf-8 -*-
"""桌面能力：点击右下角时钟展开 Windows 日期/时间面板，并抓取真实屏幕。

为什么需要单独一个模块：
  浏览器原生整页截图（Playwright 的 page.screenshot(full_page=True)）只画网页内容，
  右下角没有 Windows 任务栏，更不会展开日期/日历面板。
  用户要求「点击电脑右下角日期出来的日期及时间的界面」，只能靠真实屏幕抓取。

核心难点是定位任务栏时钟：
  Windows 11 的托盘图标数量会变，时钟整体左右漂移，固定偏移会点空（只弹出通知中心）。
  所以这里在任务栏右端做图像分析——找出最靠右的一段足够宽的深色文字簇，
  再合并字形间隙（<=8px，否则日期会被拆成一个个数字），切出时间行/日期行。

弹出后还要校验「是日历而不是通知中心」：
  通知中心顶部没有大字号时间；日历顶部有一行 >=18px 的深色行带，据此判定。
"""
from __future__ import annotations

import ctypes
import os
import time
from typing import Callable, List, Optional, Tuple
# DPI 感知必须在导入 PIL 之前设置，否则缩放屏下 ImageGrab 只能截到局部区域
def _set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetThreadDPIAware()
        except Exception:
            pass


_set_dpi_aware()

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402
from PIL import ImageGrab  # noqa: E402

_user32 = ctypes.windll.user32

# GetDpiForWindow 收 HWND（64 位进程下是 64 位），不声明 argtypes 会被截断成 32 位
_user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
_user32.GetDpiForWindow.restype = ctypes.c_uint
_user32.GetDpiForSystem.argtypes = []
_user32.GetDpiForSystem.restype = ctypes.c_uint

__all__ = [
    "find_browser_window", "activate_window", "wake_taskbar",
    "find_clock_points", "open_date_popup", "close_date_popup",
    "grab_screen", "grab_date_panel", "dpi_scale", "EXE_BY_BROWSER",
]

# ------------------------------------------------------------------ DPI 适配
# Win11 的「通知中心 + 日历」卡片是一套**固定版式**的界面元素：
# 尺寸按 DIP（设备无关像素，96 DPI = 1 英寸）定义，屏幕缩放多少就等比放大多少。
# 所以只要拿到缩放系数 k，就能在任意分辨率 / 任意缩放比例下算出卡片位置，
# 换电脑不需要改任何常量。
#
#   以下常量只是**兜底用**的先验值（主定位靠描边线检测，见 _detect_card）：
#   卡片宽约 336 DIP、高约 520 DIP、右缘距屏幕右缘 12 DIP、下缘距任务栏上沿 12 DIP
CARD_W_DIP = 336
CARD_H_DIP = 520
CARD_RIGHT_DIP = 12
CARD_BOTTOM_DIP = 12
CARD_RADIUS_DIP = 8


def dpi_scale() -> float:
    """任务栏所在显示器的缩放系数（96 DPI = 1.0）。

    取任务栏窗口的 DPI 而不是 GetDpiForSystem()：多显示器且各屏缩放比例
    不同时（常见于 4K 副屏 150%、1080p 主屏 100%），系统浮层跟随任务栏
    所在屏走，所以以任务栏为准，物理像素才能对得上。
    """
    hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
    dpi = 0
    if hwnd:
        try:
            dpi = int(_user32.GetDpiForWindow(ctypes.c_void_p(hwnd)))
        except Exception:
            dpi = 0
    if dpi <= 0:
        try:
            dpi = int(_user32.GetDpiForSystem())
        except Exception:
            dpi = 96
    return max(0.5, dpi / 96.0)


def _dip(value: float, k: float) -> int:
    """DIP -> 物理像素。"""
    return int(round(value * k))


# 浏览器可执行文件名 -> 窗口标题用的进程名
EXE_BY_BROWSER = {
    "Edge": "msedge.exe",
    "Chrome": "chrome.exe",
}


# ------------------------------------------------------------------ 窗口控制
def _process_exe(hwnd) -> str:
    """取窗口所属进程的可执行文件名（小写），失败返回空串。"""
    try:
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        ctypes.windll.kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower()
    except Exception:
        return ""


def find_browser_window(browser: str = "Edge", title_keyword: str = "") -> Optional[int]:
    """找浏览器主窗口句柄。

    按进程可执行名过滤（msedge.exe / chrome.exe），避免误命中 WorkBuddy、微信等
    同为 Chromium 内核的窗口；有标题关键字时优先取标题匹配的，否则取面积最大者。
    """
    exe_filter = EXE_BY_BROWSER.get(browser, "chrome.exe")
    found: List[Tuple[int, str, int]] = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
                return
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return
        if not title:
            return
        if _process_exe(hwnd) != exe_filter:
            return
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        found.append((hwnd, title, (r - l) * (b - t)))

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception:
        return None
    if not found:
        return None
    key = (title_keyword or "").strip()[:24]
    if key:
        for hwnd, title, _ in found:
            if key in title:
                return hwnd
    return max(found, key=lambda x: x[2])[0]


def activate_window(hwnd: int, maximize: bool = True) -> None:
    """把窗口提到前台（ALT 技巧绕开前台焦点锁定 + TOPMOST 兜底）。"""
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        if maximize:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    try:
        _user32.keybd_event(0x12, 0, 0, 0)
        _user32.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass
    time.sleep(0.4)


def wake_taskbar(log: Callable[[str], None] = print) -> None:
    """任务栏「自动隐藏」时把光标移到底部触发其弹出，否则右下角没有时间。"""
    try:
        hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
        if not hwnd:
            return
        rect = win32gui.GetWindowRect(hwnd)
        screen_h = win32api.GetSystemMetrics(1)
        if rect[1] >= screen_h - 2:  # 已隐藏到屏幕外
            win32api.SetCursorPos((win32api.GetSystemMetrics(0) // 2, screen_h - 1))
            time.sleep(0.9)
            log("  提示：任务栏为自动隐藏模式，已触发弹出")
    except Exception as exc:
        log("  提示：任务栏唤醒失败(%s)，截图可能不含任务栏时间" % exc)


# ------------------------------------------------------------------ 时钟定位
def _taskbar_rect() -> Tuple[int, int, int, int]:
    """任务栏窗口矩形 (l, t, r, b)；取不到则按主屏底部估算。"""
    hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
    if hwnd:
        return tuple(win32gui.GetWindowRect(hwnd))  # type: ignore[return-value]
    w = win32api.GetSystemMetrics(0)
    h = win32api.GetSystemMetrics(1)
    return (0, h - 48, w, h)


def _clock_cluster() -> Optional[Tuple[int, int, int, int, List[Tuple[int, int]]]]:
    """定位任务栏时钟文字簇。

    返回 (绝对左, 绝对上, 绝对右, 绝对下, 行带列表)；行带是相对簇内上边缘的
    (y0, y1)，一般为「时间行」「日期行」两条。

    做法：在任务栏右端 420px 做灰度分析，找最靠右的一段宽度 >=30px 的深色文字簇，
    再合并字形间隙（<=8px，否则日期会被拆成一个个数字），最后按行切分。
    """
    try:
        left, top, right, bottom = _taskbar_rect()
        x0 = max(0, right - 420)
        strip = ImageGrab.grab(all_screens=False).crop((x0, top, right, bottom)).convert("L")
        w, h = strip.size
        px = strip.load()
        cols = [sum(1 for y in range(h) if px[x, y] < 150) for x in range(w)]

        groups: List[Tuple[int, int]] = []
        x = 0
        while x < w:
            if cols[x] == 0:
                x += 1
                continue
            s = x
            while x < w and cols[x] > 0:
                x += 1
            groups.append((s, x - 1))

        merged: List[Tuple[int, int]] = []
        for g in groups:
            if merged and g[0] - merged[-1][1] <= 8:
                merged[-1] = (merged[-1][0], g[1])
            else:
                merged.append(g)
        groups = [g for g in merged if g[1] - g[0] >= 30]
        if not groups:
            return None
        gs, ge = groups[-1]

        rows = [y for y in range(h) if any(px[x, y] < 150 for x in range(gs, ge + 1))]
        if not rows:
            return None
        bands: List[Tuple[int, int]] = []
        s = prev = rows[0]
        for y in rows[1:]:
            if y - prev > 2:
                bands.append((s, prev))
                s = y
            prev = y
        bands.append((s, prev))
        return (x0 + gs, top + rows[0], x0 + ge + 1, top + rows[-1] + 1, bands)
    except Exception:
        return None


def find_clock_points() -> List[Tuple[int, int]]:
    """动态定位任务栏时钟（时间行 / 日期行）的可点击坐标。"""
    got = _clock_cluster()
    if not got:
        return []
    l, t, _r, _b, bands = got
    cx = (l + _r) // 2
    return [(cx, t + (bs + be) // 2) for bs, be in bands[:2]]


def _clock_points_wide() -> List[Tuple[int, int]]:
    """时钟的可点击候选点（比 find_clock_points 更宽）。

    实测踩坑：有时任务栏时钟的文字簇被拆成两段（时间 / 日期分居两块），
    或者整簇偏左/偏右，只点簇中心会点空（只弹通知中心）。
    这里在簇的左右两端各补一个候选点，提高命中率。
    """
    got = _clock_cluster()
    if not got:
        return []
    l, t, r, _b, bands = got
    pts: List[Tuple[int, int]] = []
    for bs, be in bands[:2]:
        y = t + (bs + be) // 2
        pts.append(((l + r) // 2, y))
        pts.append((l + 6, y))
        pts.append((r - 6, y))
    # 去重保序
    seen = set()
    out = []
    for p in pts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out



def _looks_like_calendar() -> bool:
    """校验右下角弹出的是「日历」而非通知中心。

    日历顶部有一行大字号时间（连续 >=18px 的深色行带）；通知中心没有。
    """
    try:
        k = dpi_scale()
        w = win32api.GetSystemMetrics(0)
        h = win32api.GetSystemMetrics(1)
        region = ImageGrab.grab(all_screens=False).crop(
            (w - _dip(620, k), h - _dip(780, k), w, h)).convert("L")
        rw, rh = region.size
        px = region.load()
        band = 0
        for y in range(rh):
            if any(px[x, y] < 120 for x in range(0, rw, 2)):
                band += 1
            else:
                if band >= _dip(18, k):
                    return True
                band = 0
        return band >= _dip(18, k)
    except Exception:
        return False


def _click_xy(x: int, y: int) -> None:
    _user32.SetCursorPos(x, y)
    time.sleep(0.2)
    _user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.06)
    _user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def close_date_popup() -> None:
    """关闭日期/通知中心面板（ESC），避免遮挡后续操作。

    说明：Win11 24H2 点击右下角时钟弹出的是「通知 + 日历」合并浮层
    （通知列表在上、日历在下），这是系统标准形态，无法单独收起通知列表。
    """
    try:
        _user32.keybd_event(0x1B, 0, 0, 0)
        _user32.keybd_event(0x1B, 0, 2, 0)
        time.sleep(0.3)
    except Exception:
        pass


def open_date_popup(log: Callable[[str], None] = print, settle: float = 0.9,
                    rounds: int = 3) -> bool:
    """点击右下角时钟，展开日期/时间面板。返回是否成功弹出日历。

    依次尝试：图像分析得到的时钟候选点（时间行 -> 日期行 -> 簇两端）
    -> Win+A 兜底，每轮都重新定位一次（时钟会随窗口状态微移），
    并用「大字号时间」特征校验，避免只打开了通知中心却误判为成功。

    用户反馈「有些不能弹出日期详情」——多数是**只弹出了通知中心**
    （Win11 24H2 里点通知铃铛就是这个），所以这里对每个候选点都做校验，
    校验不过就换点、换轮次重试。
    """
    for rnd in range(1, max(1, int(rounds)) + 1):
        points = _clock_points_wide() or find_clock_points()
        if not points:
            log("  提示：未能定位任务栏时钟，改用快捷键 Win+A")
        close_date_popup()
        time.sleep(0.25)
        for x, y in points:
            _click_xy(x, y)
            time.sleep(settle)
            if _looks_like_calendar():
                return True
            close_date_popup()
            time.sleep(0.2)
        # Win+A 兜底
        try:
            _user32.keybd_event(0x5B, 0, 0, 0)
            _user32.keybd_event(0x41, 0, 0, 0)
            _user32.keybd_event(0x41, 0, 2, 0)
            _user32.keybd_event(0x5B, 0, 2, 0)
            time.sleep(settle + 0.2)
            if _looks_like_calendar():
                return True
            close_date_popup()
        except Exception:
            pass
        log("  ↻ 第 %d 轮未能展开日期面板，重试" % rnd)
    return False


def grab_screen(path: str) -> str:
    """抓取真实屏幕并落盘（含任务栏与日期面板）。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    img = ImageGrab.grab(all_screens=False)
    img.save(path)
    return path


def _dips(vals, depth: int = 22) -> List[int]:
    """找出序列里的局部极小点（下标），即「比左右邻居都暗 depth 以上」的像素。"""
    n = len(vals)
    out: List[int] = []
    for i in range(1, n - 1):
        v = int(vals[i])
        if v < int(vals[i - 1]) - depth and v < int(vals[i + 1]) - depth:
            out.append(i)
    return out


def _time_bands(g, sw: int, sh: int, k: float, tb_t: int) -> List[Tuple[int, int, int, int]]:
    """在右下角 ROI 里找「大字号时间」候选行带。

    Win11 日历卡片顶部那行 "HH:MM:SS" 特征极强：
      - 字号大：字高 >= 13 DIP（任务栏时钟只有 ~9 DIP，正文更小）
      - 右侧留白：时间右边直到卡片右缘是大片空白
    返回按 y 从小到大排序的候选列表 [(x0, y0, x1, y1), ...]。
    """
    try:
        import numpy as np
    except Exception:
        return []
    x0 = max(0, int(sw - 760 * k))
    y0 = max(0, int(tb_t - 860 * k))
    # 只搜卡片的上半部分：日历网格里的"选中日期圆点"是整块实心，
    # 高度比时间还大，靠 y 范围把它排除掉。
    y1 = max(y0 + 20, int(tb_t - 240 * k))
    if y1 > sh:
        y1 = sh
    sub = g[y0:y1, x0:sw] < 110
    rowcnt = sub.sum(axis=1)
    bands: List[Tuple[int, int]] = []
    s = None
    for i, c in enumerate(rowcnt):
        if c >= 2:
            if s is None:
                s = i
        else:
            if s is not None:
                bands.append((s, i - 1))
                s = None
    if s is not None:
        bands.append((s, len(rowcnt) - 1))

    h_min = _dip(13, k)
    h_max = _dip(52, k)
    w_min = _dip(40, k)
    w_max = _dip(300, k)
    blank_min = _dip(35, k)
    out: List[Tuple[int, int, int, int]] = []
    for bs, be in bands:
        bh = be - bs + 1
        if bh < h_min or bh > h_max:
            continue
        strip = sub[bs:be + 1]
        nz = np.nonzero(strip.sum(axis=0))[0]
        if nz.size == 0:
            continue
        cl, cr = int(nz[0]), int(nz[-1])
        if cr - cl + 1 < w_min or cr - cl + 1 > w_max:
            continue
        blank = int((~strip[:, cr + 1:].any(axis=0)).sum())
        if blank < blank_min:
            continue
        out.append((x0 + cl, y0 + bs, x0 + cr + 1, y0 + be + 1))
    out.sort(key=lambda b: b[1])
    return out


def _detect_card(g, sw: int, sh: int, tb_t: int, k: float,
                 band: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """已知大字号时间行带，反推卡片四条描边线，返回 (l, t, r, b)。

    原理：卡片是带 1px 描边的圆角矩形，描边比卡片内部背景更暗，
    在灰度图上表现为「局部极小值」。从时间锚点向四个方向找描边即可，
    **完全不依赖屏幕分辨率、缩放比例或卡片尺寸**。
    """
    tx0, ty0, tx1, ty1 = band

    # 水平剖面：取时间行带内每列的最亮像素，跳过字形笔画，只留背景与描边
    strip = g[ty0:ty1 + 1, :]
    prof = strip.max(axis=0)

    # 左描边：时间左边最近的极小值
    lo = max(0, tx0 - _dip(160, k))
    dl = _dips(prof[lo:tx0])
    if not dl:
        return None
    left = lo + dl[0]

    # 右描边：时间右边最远的极小值（取"最远"是为了跳过卡片内的下拉箭头）
    hi = min(sw, tx1 + _dip(480, k))
    dr = _dips(prof[tx1:hi])
    if not dr:
        return None
    right = tx1 + dr[-1]

    # 竖直方向用卡片左描边内侧的列，这一列在卡片内基本是空白
    col_x = min(sw - 2, left + _dip(12, k))

    # 上描边：时间上边往上扫到底，取**最高**的极小值
    y_top_limit = max(0, ty0 - _dip(760, k))
    dt = _dips(g[y_top_limit:ty0, col_x])
    if not dt:
        return None
    top = y_top_limit + dt[-1]

    # 下描边：从任务栏上沿往下扫，取**第一个**极小值
    y_bot_limit = min(sh, tb_t)
    db = _dips(g[ty1:y_bot_limit, col_x])
    if not db:
        return None
    bottom = ty1 + db[0]

    if right - left < _dip(150, k) or bottom - top < _dip(240, k):
        return None
    # 时间必须紧贴卡片左缘（卡片内边距只有十几 DIP）
    gap = (tx0 - left) / k
    if gap < 5 or gap > 60:
        return None
    return (left, top, right + 1, bottom + 1)


def _locate_date_card(img, tb, k: float, log: Callable[[str], None] = print
                      ) -> Optional[Tuple[int, int, int, int]]:
    """在整屏截图里定位 Win11 日历卡片，返回屏幕矩形 (l, t, r, b)。

    主路径：**描边线检测**（跨分辨率 / 跨缩放 / 跨 Windows 版本都适用）
      1. 先在右下角找到大字号时间 "HH:MM:SS" 行带，保证落在卡片内部靠上靠左
      2. 从时间向左右找卡片的左右描边线
      3. 在卡片左描边内侧的列上，向上找上描边、向下找下描边
      4. 每个候选行带都做一次自校验（尺寸是否合理、时间是否紧贴左缘），
         第一个通过的即采用

    兜底路径：几何模型（DIP 换算），只在描边检测完全失败时启用。

    全程只读系统信息，不修改任何设置。
    """
    try:
        import numpy as np
    except Exception:
        return None
    sw, sh = img.size
    tb_l, tb_t, tb_r, tb_b = tb
    if tb_r > sw or tb_b > sh:
        # 任务栏不在本截图范围内（多显示器），本屏拿不到浮层
        return None

    g = np.asarray(img.convert("L"), dtype=np.int16)
    for band in _time_bands(g, sw, sh, k, tb_t):
        rect = _detect_card(g, sw, sh, tb_t, k, band)
        if not rect:
            continue
        l, t, r, b = rect
        w_dip = (r - l) / k
        h_dip = (b - t) / k
        if 240 <= w_dip <= 460 and 340 <= h_dip <= 700:
            log("  ✔ 日历卡片定位成功：%dx%d DIP，位于 (%d, %d)"
                % (w_dip, h_dip, l, t))
            return rect
        log("  提示：候选卡片尺寸 %dx%d DIP 不合理，换下一个候选"
            % (w_dip, h_dip))

    # ---- 兜底：几何模型 ----
    card_right = sw - _dip(CARD_RIGHT_DIP, k)
    card_bottom = tb_t - _dip(CARD_BOTTOM_DIP, k)
    card_top = card_bottom - _dip(CARD_H_DIP, k)
    card_left = card_right - _dip(CARD_W_DIP, k)
    if card_left < 0 or card_top < 0:
        log("  ⚠ 描边检测失败，且几何兜底框越界")
        return None
    log("  ⚠ 描边检测失败，改用几何兜底框（%dx%d DIP）"
        % (CARD_W_DIP, CARD_H_DIP))
    return (card_left, card_top, card_right, card_bottom)


def _round_mask(size: Tuple[int, int], radius: int) -> "Image":
    """生成圆角矩形遮罩（RGBA 的 alpha 通道）。"""
    from PIL import Image, ImageDraw
    w, h = size
    r = max(0, min(radius, w // 2, h // 2))
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return mask


def grab_date_panel(path: str, log: Callable[[str], None] = print
                    ) -> Optional[Tuple[str, Tuple[int, int, int, int], float]]:
    """展开系统日期/时间面板，把「面板本身」单独抓下来。

    为什么不能直接截整屏：整屏里浏览器只占一屏，页面内容看不全，
    而这里要的是「完整的页面原图 + 右下角的日期面板」。

    定位方式（不依赖任何绝对像素，跨分辨率/跨缩放自适应）：
      - 卡片版式按 DIP 换算（dpi_scale() 读任务栏所在显示器的 DPI）
      - 再用卡片内「大字号时间」这一内容锚点修正左缘/上缘
      - 任务栏居中/左对齐时，右缘锚定到时钟本身

    失败常见原因（用户反馈「有些不能弹出日期详情」）：
      - 浏览器窗口不在前台 —— 系统浮层会被别的窗口挡住，截不到；
      - 上一次的面板还开着 —— 状态是「已展开」，再点会先收起。
    所以这里先关掉已有浮层，并重试若干轮。

    返回 (图片路径, 屏幕矩形, 缩放系数)；没弹出面板时返回 None。
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

    k = dpi_scale()
    tb = _taskbar_rect()
    # 任务栏自动隐藏时先把它唤出来，否则右下角根本没有时钟
    wake_taskbar(log)
    close_date_popup()
    time.sleep(0.4)

    opened = False
    for attempt in range(1, 4):
        if open_date_popup(log):
            opened = True
            break
        log("  ↻ 第 %d 次未能展开日期面板，重试" % attempt)
        time.sleep(0.8)
    if not opened:
        log("  ⚠ 日期面板未能展开，本次仅保留页面原图")
        return None

    time.sleep(0.8)
    screen = ImageGrab.grab(all_screens=False).convert("RGB")
    rect = _locate_date_card(screen, tb, k, log)
    close_date_popup()
    if not rect:
        log("  ⚠ 未定位到日期面板，本次仅保留页面原图")
        return None

    l, t, r, b = rect
    l = max(0, l)
    t = max(0, t)
    r = min(screen.width, r)
    b = min(screen.height, b)
    if r - l < 60 or b - t < 60:
        log("  ⚠ 检出的日期面板区域过小（%dx%d），本次仅保留页面原图" % (r - l, b - t))
        return None

    panel = screen.crop((l, t, r, b)).convert("RGBA")
    panel.putalpha(_round_mask(panel.size, _dip(CARD_RADIUS_DIP, k)))
    panel.save(path)
    return path, (l, t, r, b), k
