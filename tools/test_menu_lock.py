# -*- coding: utf-8 -*-
"""验证「固定位置大小」：锁定后滚轮不该改变直径；再点一次解锁后滚轮应生效。"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

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


def size(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.r - r.l, r.b - r.t


def menu_item(hwnd, cx, cy, item):
    """相对菜单左上角点第 item 项（1=第一项）"""
    user32.SetCursorPos(cx, cy)
    time.sleep(0.2)
    user32.PostMessageW(hwnd, 0x0205, 0, 0)
    time.sleep(0.8)
    user32.SetCursorPos(cx + 70, cy + 12 + (item - 1) * 22)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.8)


def wheel(hwnd, up=True):
    wp = ((120 if up else -120) & 0xFFFF) << 16
    user32.PostMessageW(hwnd, 0x020A, wp, 0)
    time.sleep(0.6)


hwnd = find()
if not hwnd:
    print("NO_WINDOW")
    raise SystemExit(2)
r = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
cx, cy = (r.l + r.r) // 2, (r.t + r.b) // 2
print("start size:", size(hwnd))

menu_item(hwnd, cx, cy, 2)          # 固定
s0 = size(hwnd)
wheel(hwnd, True)
s1 = size(hwnd)
print("locked  : %s -> %s  %s" % (s0, s1, "被锁住(OK)" if s0 == s1 else "还能缩放(BAD)"))

menu_item(hwnd, cx, cy, 2)          # 解除固定
s2 = size(hwnd)
wheel(hwnd, True)
s3 = size(hwnd)
print("unlocked: %s -> %s  %s" % (s2, s3, "能缩放(OK)" if s2 != s3 else "没反应(BAD)"))
print("RESULT:", "PASS" if (s0 == s1 and s2 != s3) else "FAIL")
