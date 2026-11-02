#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给浮窗发滚轮消息，验证变焦：/ 看相机档位，顺便截前后快照。"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
import urllib.request

u = ctypes.WinDLL("user32", use_last_error=True)
WM_MOUSEWHEEL = 0x020A


def find_window(title_part="CamBubble"):
    hits = []
    E = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, _):
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            u.GetWindowTextW(h, b, n + 2)
            if title_part in b.value:
                hits.append(h)
        return True

    u.EnumWindows(E(cb), 0)
    return hits


def status(url_base):
    with urllib.request.urlopen(url_base + "/", timeout=5) as r:
        return r.read().decode("ascii", "ignore")


def zoom_of(txt):
    for line in txt.splitlines():
        if line.startswith("zoom="):
            return line.strip()
    return "?"


def wheel(hwnd, notches):
    for _ in range(abs(notches)):
        delta = 120 if notches > 0 else -120
        u.PostMessageW(hwnd, WM_MOUSEWHEEL, (delta & 0xFFFF) << 16, 0)
        time.sleep(0.12)


def snap(url_base, path):
    with urllib.request.urlopen(url_base + "/snapshot", timeout=8) as r:
        data = r.read()
    open(path, "wb").write(data)
    return len(data)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.31.130:8088"
    wins = find_window()
    if not wins:
        raise SystemExit("没找到浮窗")
    hwnd = wins[0]
    print("hwnd =", hex(hwnd))
    print("before :", zoom_of(status(base)))
    snap(base, r"E:\ai_project\redmik20\build\zoom_before.jpg")

    wheel(hwnd, 4)
    time.sleep(1.2)
    print("wheel+4:", zoom_of(status(base)))
    n2 = snap(base, r"E:\ai_project\redmik20\build\zoom_after.jpg")

    wheel(hwnd, -4)
    time.sleep(1.2)
    print("wheel-4:", zoom_of(status(base)))
    print("after snapshot bytes =", n2)


if __name__ == "__main__":
    main()
