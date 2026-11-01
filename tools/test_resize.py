# -*- coding: utf-8 -*-
"""对运行中的 CamBubble 自动发滚轮消息，验证「圆形大小可调」真的生效。
用法: python tools/test_resize.py [--delta 120] [--times 3]
输出每一步的窗口尺寸（物理像素），最后判断是否按 20px/格 变化。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND


def find_windows(title):
    hits = []

    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(hwnd, buf, n + 2)
            if title in buf.value and user32.IsWindowVisible(hwnd):
                hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return hits


def rect(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.r - r.l, r.b - r.t, r.l, r.t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="CamBubble")
    ap.add_argument("--delta", type=int, default=120)
    ap.add_argument("--times", type=int, default=3)
    args = ap.parse_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()

    hits = find_windows(args.title)
    if not hits:
        print("没找到窗口:", args.title)
        return 2
    hwnd, title = hits[0]
    print("hwnd=0x%X title=%s exstyle=0x%X (TOPMOST=%s)" % (
        hwnd, title, user32.GetWindowLongW(hwnd, -20),
        bool(user32.GetWindowLongW(hwnd, -20) & 0x8)))

    w, h, x, y = rect(hwnd)
    print("start  %dx%d at (%d,%d)" % (w, h, x, y))
    sizes = [(w, h)]
    for i in range(args.times):
        wp = (args.delta & 0xFFFF) << 16          # 高字 = 滚轮增量
        user32.PostMessageW(hwnd, 0x020A, wp, 0)  # WM_MOUSEWHEEL
        time.sleep(0.45)
        w, h, x, y = rect(hwnd)
        print("wheel+ %d -> %dx%d at (%d,%d)" % (i + 1, w, h, x, y))
        sizes.append((w, h))
    for i in range(args.times):
        wp = ((-args.delta) & 0xFFFF) << 16
        user32.PostMessageW(hwnd, 0x020A, wp, 0)
        time.sleep(0.45)
        w, h, x, y = rect(hwnd)
        print("wheel- %d -> %dx%d at (%d,%d)" % (i + 1, w, h, x, y))
        sizes.append((w, h))

    up = all(sizes[i + 1][0] == sizes[i][0] + 20 for i in range(args.times))
    down = all(sizes[args.times + 1 + i][0] == sizes[args.times + i][0] - 20
               for i in range(args.times))
    print("resize-step+20:", up, " resize-step-20:", down)
    print("final:", sizes[-1])
    return 0 if (up and down) else 1


if __name__ == "__main__":
    raise SystemExit(main())
