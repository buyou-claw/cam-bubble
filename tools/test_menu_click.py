# -*- coding: utf-8 -*-
"""用鼠标点菜单项来验证（键盘事件对 TPM_RETURNCMD 的弹出菜单不一定生效）。"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import sys
import time

from PIL import ImageGrab

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
user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


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


def click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def bhash(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    img = ImageGrab.grab(bbox=(r.l + 10, r.t + 10, r.r - 10, r.b - 10))
    return hashlib.sha256(img.tobytes()).hexdigest()[:12], img


hwnd = find()
if not hwnd:
    print("NO_WINDOW")
    raise SystemExit(2)
r = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
cx, cy = (r.l + r.r) // 2, (r.t + r.b) // 2
print("hwnd=0x%X rect=(%d,%d)-(%d,%d) center=(%d,%d)" % (hwnd, r.l, r.t, r.r, r.b, cx, cy))

# 开菜单
user32.SetCursorPos(cx, cy)
time.sleep(0.2)
user32.PostMessageW(hwnd, 0x0205, 0, 0)
time.sleep(0.9)
# 点第一项（菜单左上角就在鼠标位置，第一项大约在 +12px）
click(cx + 70, cy + 12)
time.sleep(1.0)

h1, img1 = bhash(hwnd)
time.sleep(2.0)
h2, _ = bhash(hwnd)
paused = (h1 == h2)
print("after-click-1:", h1, h2, "paused=", paused)
img1.save(r"E:\ai_project\redmik20\evidence\menu_paused.png")

# 再点一次恢复
user32.SetCursorPos(cx, cy)
time.sleep(0.2)
user32.PostMessageW(hwnd, 0x0205, 0, 0)
time.sleep(0.9)
click(cx + 70, cy + 12)
time.sleep(1.0)
h3, _ = bhash(hwnd)
time.sleep(2.0)
h4, _ = bhash(hwnd)
print("after-click-2:", h3, h4, "resumed=", h3 != h4)
print("RESULT:", "PASS" if (paused and h3 != h4) else "FAIL")
