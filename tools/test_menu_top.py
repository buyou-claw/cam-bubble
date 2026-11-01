# -*- coding: utf-8 -*-
"""验证「取消置顶 / 恢复置顶」：直接读 WS_EX_TOPMOST 位。"""
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()


def find(title="CamBubble"):
    hits = []

    def cb(h, _):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            if title in b.value:
                hits.append(h)
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return hits[0] if hits else None


def topmost(hwnd):
    return bool(user32.GetWindowLongW(hwnd, -20) & 0x8)


def pick(hwnd, item):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    cx, cy = (r.l + r.r) // 2, (r.t + r.b) // 2
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(cx, cy)
    time.sleep(0.2)
    user32.PostMessageW(hwnd, 0x0205, 0, 0)
    time.sleep(0.9)
    x = min(cx, sw - 260) + 60
    y = min(cy, sh - 250) + 14 + (item - 1) * 28
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.9)


hwnd = find()
if not hwnd:
    print("NO_WINDOW")
    raise SystemExit(2)
print("初始 TOPMOST:", topmost(hwnd))
pick(hwnd, 3)          # 取消置顶
t1 = topmost(hwnd)
print("点『取消置顶』后:", t1)
pick(hwnd, 3)          # 恢复置顶
t2 = topmost(hwnd)
print("点『恢复置顶』后:", t2)
print("RESULT:", "PASS" if (not t1 and t2) else "FAIL")
