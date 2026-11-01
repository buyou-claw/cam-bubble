# -*- coding: utf-8 -*-
"""给 CamBubble 发一次右键，截屏看菜单，然后按 Esc 关掉。"""
import ctypes
import ctypes.wintypes as wt
import subprocess
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

title = sys.argv[1] if len(sys.argv) > 1 else "CamBubble"
out = sys.argv[2] if len(sys.argv) > 2 else r"E:\ai_project\redmik20\evidence\menu.png"

hits = []


def cb(hwnd, _):
    n = user32.GetWindowTextLengthW(hwnd)
    if n:
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        if title in buf.value:
            hits.append(hwnd)
    return True


user32.EnumWindows(EnumProc(cb), 0)
if not hits:
    print("没找到窗口", title)
    raise SystemExit(2)

hwnd = hits[0]
r = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
cx, cy = (r.l + r.r) // 2, (r.t + r.b) // 2
print("hwnd=0x%X rect=(%d,%d)-(%d,%d) center=(%d,%d)" % (hwnd, r.l, r.t, r.r, r.b, cx, cy))

user32.SetCursorPos(cx, cy)
time.sleep(0.2)
user32.PostMessageW(hwnd, 0x0205, 0, 0)   # WM_RBUTTONUP
print("posted WM_RBUTTONUP")
time.sleep(1.0)

subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", r"E:\ai_project\redmik20\evidence\proof_topmost.ps1",
                "-Title", title, "-Out", out],
               capture_output=True)
print("screenshot ->", out)

# 关掉菜单：连按两次 Esc（keybd_event 走系统输入队列）
for _ in range(2):
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 2, 0)
    time.sleep(0.15)
print("esc sent")
