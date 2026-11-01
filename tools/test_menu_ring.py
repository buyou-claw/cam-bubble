# -*- coding: utf-8 -*-
"""用「描边颜色」判定状态：白=正常，黄=暂停，橙=固定。比对比帧哈希可靠（静态场景不会变）。"""
import ctypes
import ctypes.wintypes as wt
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


def rect(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.l, r.t, r.r, r.b


def ring_rgb(hwnd):
    l, t, r, b = rect(hwnd)
    cx = (l + r) // 2
    img = ImageGrab.grab(bbox=(cx - 2, t, cx + 3, t + 4))
    px = list(img.getdata())
    # 取最亮/最饱和的那颗当描边色
    best = max(px, key=lambda p: sum(p))
    return best, (l, t, r, b)


def click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def pick_item(hwnd, item):
    l, t, r, b = rect(hwnd)
    cx, cy = (l + r) // 2, (t + b) // 2
    user32.SetCursorPos(cx, cy)
    time.sleep(0.2)
    user32.PostMessageW(hwnd, 0x0205, 0, 0)   # 开菜单
    time.sleep(0.9)
    # 菜单左上角在鼠标处；屏幕右/下不够时 Windows 会自动挪，按屏幕边界修正
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    menu_w, menu_h = 260, 240
    mx = min(cx, sw - menu_w)
    my = min(cy, sh - menu_h)
    click(mx + 60, my + 12 + (item - 1) * 22)
    time.sleep(0.9)


hwnd = find()
if not hwnd:
    print("NO_WINDOW")
    raise SystemExit(2)

color0, box = ring_rgb(hwnd)
print("初始描边:", color0, "窗口:", box)

pick_item(hwnd, 1)     # 暂停
c1, _ = ring_rgb(hwnd)
print("点『暂停画面』后:", c1)
pick_item(hwnd, 1)     # 继续
c2, _ = ring_rgb(hwnd)
print("点『继续画面』后:", c2)

pick_item(hwnd, 2)     # 固定
c3, _ = ring_rgb(hwnd)
print("点『固定位置大小』后:", c3)
pick_item(hwnd, 2)     # 解除固定
c4, _ = ring_rgb(hwnd)
print("点『解除固定』后:", c4)

ok_pause = c1[0] > 200 and c1[1] > 150 and c1[2] < 120      # 黄色
ok_resume = c2[2] > 200 and abs(c2[0] - c2[1]) < 30          # 白色
ok_lock = c3[0] > 200 and 100 < c3[1] < 190 and c3[2] < 120  # 橙色
ok_unlock = c4[2] > 200
print("RESULT:", "PASS" if (ok_pause and ok_resume and ok_lock and ok_unlock) else "FAIL",
      dict(pause=ok_pause, resume=ok_resume, lock=ok_lock, unlock=ok_unlock))
