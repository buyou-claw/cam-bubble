#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cam_bubble.py - 圆形摄像头浮窗（永远置顶 / 滚轮自由缩放 / 拖动移动）

数据源（三选一）:
  --url http://192.168.31.130:4747/video   手机摄像头 MJPEG 流（DroidCam / IP Webcam）
  --test                                   本地合成画面，自检用（不需要手机）
  --jpeg-dir DIR                           读取目录里最新的 jpg（自定义推流用）

交互:
  滚轮上/下     圆形直径 +/- 20px
  左键拖动      移动窗口
  右键          退出
  Esc           退出（窗口有焦点时）

原理: Win32 分层窗口(WS_EX_LAYERED) + UpdateLayeredWindow 预乘 alpha，
      真正逐像素透明 => 圆外完全透明，且窗口始终 WS_EX_TOPMOST。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- Win32 定义
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", POINT)]


# ---------------------------------------------------------------- 原型声明
# 64 位下必须显式给 restype/argtypes，否则句柄会被截断成 32 位
def _proto(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


TOP = wt.HWND(-1)
_proto(user32.RegisterClassExW, wt.WORD, ctypes.POINTER(WNDCLASSEXW))
_proto(user32.CreateWindowExW, wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
_proto(user32.DefWindowProcW, ctypes.c_longlong, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_proto(user32.GetMessageW, ctypes.c_int, ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT)
_proto(user32.TranslateMessage, wt.BOOL, ctypes.POINTER(MSG))
_proto(user32.DispatchMessageW, ctypes.c_longlong, ctypes.POINTER(MSG))
_proto(user32.PostQuitMessage, None, ctypes.c_int)
_proto(user32.GetDC, wt.HDC, wt.HWND)
_proto(user32.UpdateLayeredWindow, wt.BOOL, wt.HWND, wt.HDC,
       ctypes.POINTER(POINT), ctypes.POINTER(SIZE), wt.HDC, ctypes.POINTER(POINT),
       wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD)
_proto(user32.SetWindowPos, wt.BOOL, wt.HWND, wt.HWND,
       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)
_proto(user32.SetTimer, ctypes.c_size_t, wt.HWND, ctypes.c_size_t, wt.UINT, wt.HANDLE)
_proto(user32.KillTimer, wt.BOOL, wt.HWND, ctypes.c_size_t)

# --- 右键菜单 ---
_proto(user32.CreatePopupMenu, wt.HMENU)
_proto(user32.AppendMenuW, wt.BOOL, wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR)
_proto(user32.TrackPopupMenu, ctypes.c_int, wt.HMENU, wt.UINT,
       ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p)
_proto(user32.DestroyMenu, wt.BOOL, wt.HMENU)
_proto(user32.PostMessageW, wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_proto(user32.SetForegroundWindow, wt.BOOL, wt.HWND)
_proto(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(POINT))

MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RETURNCMD = 0x0100
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTALIGN = 0x0008
TPM_RIGHTBUTTON = 0x0002
HWND_NOTOPMOST = wt.HWND(-2)
_proto(user32.ShowWindow, wt.BOOL, wt.HWND, ctypes.c_int)
_proto(user32.SetCapture, wt.HWND, wt.HWND)
_proto(user32.ReleaseCapture, wt.BOOL)
_proto(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(POINT))
_proto(user32.LoadCursorW, wt.HCURSOR, wt.HINSTANCE, ctypes.c_void_p)
_proto(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_proto(user32.SetProcessDPIAware, wt.BOOL)
_proto(gdi32.CreateDIBSection, wt.HBITMAP, wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD)
_proto(gdi32.CreateCompatibleDC, wt.HDC, wt.HDC)
_proto(gdi32.SelectObject, wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
_proto(gdi32.DeleteObject, wt.BOOL, wt.HGDIOBJ)
_proto(gdi32.DeleteDC, wt.BOOL, wt.HDC)
_proto(kernel32.GetModuleHandleW, wt.HMODULE, wt.LPCWSTR)


# ---------------------------------------------------------------- 画面源
class FrameSource:
    """最新的 RGB 帧（线程安全，只保留最后一帧）"""

    def __init__(self):
        self._img = None
        self._lock = threading.Lock()
        self._stop = False
        self.reader = None
        self.status = "init"
        self.frames = 0

    def set(self, img):
        with self._lock:
            self._img = img
            self.frames += 1

    def get(self):
        with self._lock:
            return self._img

    def stop(self):
        self._stop = True


def _decode(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def mjpeg_reader(src: FrameSource, url: str):
    """解析 multipart MJPEG（不看 boundary，直接找 SOI/EOI）"""
    backoff = 0.5
    while not src._stop:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CamBubble/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                src.status = "streaming"
                buf = b""
                backoff = 0.3
                while not src._stop:
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > 8_000_000:          # 防御性截断
                        buf = buf[-4_000_000:]
                    while True:
                        s = buf.find(b"\xff\xd8")
                        e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                        if s >= 0 and e > s:
                            try:
                                src.set(_decode(buf[s:e + 2]))
                            except Exception:
                                pass
                            buf = buf[e + 2:]
                        else:
                            break
        except Exception as exc:
            src.status = "reconnect: %s" % exc.__class__.__name__
            time.sleep(backoff)
            backoff = min(backoff * 1.6, 3.0)


def adb_h264_reader(src: FrameSource, adb: str, serial: str, ffmpeg: str,
                    screen_size: str, crop: str, bitrate: str = "8M"):
    """adb screenrecord(H.264) -> ffmpeg 解码裁剪 -> rgb24 帧

    不需要在手机上装任何 App：直接录手机屏幕（相机 App 的前台预览），
    再裁出中间的正方形送进圆形遮罩。screenrecord 有 170s 上限，这里自动续。
    """
    import subprocess

    sw, sh = [int(v) for v in screen_size.lower().split("x")]
    if crop:
        m = crop.lower().replace("+", ":").split(":")
        cw, ch, cx, cy = (int(v) for v in m[:4])
    else:                                    # 默认取屏幕正中的正方形
        cw = ch = min(sw, sh)
        cx, cy = (sw - cw) // 2, (sh - ch) // 2
    cw -= cw % 2
    ch -= ch % 2
    vf = "crop=%d:%d:%d:%d" % (cw, ch, cx, cy)
    frame_bytes = cw * ch * 3

    while not src._stop:
        adb_cmd = [adb]
        if serial:
            adb_cmd += ["-s", serial]
        adb_cmd += ["exec-out", "screenrecord", "--output-format=h264",
                    "--bit-rate", bitrate, "--size", "%dx%d" % (sw, sh),
                    "--time-limit", "170", "-"]
        ff_cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
                  "-probesize", "1000000", "-analyzeduration", "0",
                  "-f", "h264", "-i", "pipe:0",
                  "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        pa = pf = None
        try:
            pa = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            pf = subprocess.Popen(ff_cmd, stdin=pa.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            pa.stdout.close()
            src.status = "adb-screenrecord %dx%d crop %s" % (sw, sh, vf)
            while not src._stop:
                buf = pf.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                src.set(Image.frombytes("RGB", (cw, ch), buf))
        except Exception as exc:
            src.status = "adb error: %s" % exc.__class__.__name__
            time.sleep(1.0)
        finally:
            for p in (pf, pa):
                if p is not None:
                    try:
                        p.terminate()
                    except Exception:
                        pass
            time.sleep(0.4)


def jpeg_dir_reader(src: FrameSource, folder: str):
    last = None
    while not src._stop:
        try:
            files = [os.path.join(folder, f) for f in os.listdir(folder)
                     if f.lower().endswith((".jpg", ".jpeg"))]
            if files:
                newest = max(files, key=os.path.getmtime)
                if newest != last:
                    last = newest
                    with open(newest, "rb") as fh:
                        src.set(_decode(fh.read()))
                    src.status = "file: " + os.path.basename(newest)
        except Exception as exc:
            src.status = "error: %s" % exc.__class__.__name__
        time.sleep(0.05)


def test_reader(src: FrameSource):
    """合成画面：彩色渐变 + 秒表，用来验证窗口/遮罩/缩放全链路"""
    w, h = 720, 720
    t0 = time.time()
    while not src._stop:
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        for y in range(0, h, 8):
            k = y / h
            d.rectangle([0, y, w, y + 8], fill=(int(40 + 180 * k), int(90 + 90 * (1 - k)), 200))
        ang = (time.time() - t0) * 90
        cx, cy, r = w // 2, h // 2, 210
        import math
        x = cx + int(r * math.cos(math.radians(ang)))
        y = cy + int(r * math.sin(math.radians(ang)))
        d.ellipse([x - 40, y - 40, x + 40, y + 40], fill=(255, 240, 0))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=6)
        d.text((20, 20), "CamBubble TEST  %.1fs" % (time.time() - t0), fill=(255, 255, 255))
        d.text((20, h - 40), "wheel=resize  drag=move  right-click=quit", fill=(255, 255, 255))
        src.set(img)
        src.status = "test"
        time.sleep(1 / 30)


# ---------------------------------------------------------------- 主窗口
class Bubble:
    def __init__(self, args, src: FrameSource):
        self.args = args
        self.src = src
        self.size = max(80, int(args.size))
        self.x, self.y = int(args.x), int(args.y)
        self.cfg_path = args.config
        self._drag = None
        self._mask_cache = {}
        self._dib = None
        self._dib_bits = None
        self._memdc = None
        self._screen_dc = None
        self._hwnd = None
        self._proc = WNDPROC(self._wndproc)
        # 右键菜单状态
        self.paused = False
        self.locked = False
        self.topmost = True
        self.mirror = bool(getattr(args, "mirror", True))
        self.frozen = None

    # -- 配置
    def load_cfg(self):
        if not self.cfg_path or not os.path.exists(self.cfg_path):
            return
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as fh:
                c = json.load(fh)
            self.size = int(c.get("size", self.size))
            self.x = int(c.get("x", self.x))
            self.y = int(c.get("y", self.y))
        except Exception:
            pass

    def save_cfg(self):
        if not self.cfg_path:
            return
        try:
            with open(self.cfg_path, "w", encoding="utf-8") as fh:
                json.dump({"size": self.size, "x": self.x, "y": self.y}, fh)
        except Exception:
            pass

    # -- 遮罩 / 合成
    def mask(self, size):
        if size not in self._mask_cache:
            ss = 4
            m = Image.new("L", (size * ss, size * ss), 0)
            ImageDraw.Draw(m).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
            self._mask_cache[size] = m.resize((size, size), Image.LANCZOS)
        return self._mask_cache[size]

    def compose(self, size):
        if self.paused and self.frozen is not None:
            frame = self.frozen
        else:
            frame = self.src.get()
        if frame is None:
            frame = Image.new("RGB", (max(size, 240), max(size, 240)), (22, 24, 30))
            d = ImageDraw.Draw(frame)
            d.text((14, 14), "waiting for phone", fill=(210, 210, 220))
            d.text((14, 32), str(getattr(self.src, "status", ""))[:34], fill=(150, 155, 170))
        w, h = frame.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        if self.args.rotation:
            frame = frame.rotate(self.args.rotation, expand=True)
            w, h = frame.size
            side = min(w, h)
            left, top = (w - side) // 2, (h - side) // 2
        if self.mirror:
            frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
        sq = frame.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
        rg = sq.convert("RGBA")
        rg.putalpha(self.mask(size))
        if self.args.border > 0:
            bw = max(1, int(round(self.args.border)))
            off = bw // 2
            # 白=正常 橙=固定 黄=暂停 灰=未置顶
            if self.paused:
                ring = (240, 200, 60, 255)
            elif self.locked:
                ring = (255, 150, 60, 255)
            elif not self.topmost:
                ring = (160, 160, 160, 255)
            else:
                ring = (255, 255, 255, 255)
            ImageDraw.Draw(rg).ellipse((off, off, size - 1 - off, size - 1 - off),
                                       outline=ring, width=bw)
        a = np.asarray(rg, dtype=np.uint16)
        alpha = a[..., 3].astype(np.float32) / 255.0
        bgra = np.empty((size, size, 4), dtype=np.uint8)
        bgra[..., 0] = (a[..., 2] * alpha).astype(np.uint8)
        bgra[..., 1] = (a[..., 1] * alpha).astype(np.uint8)
        bgra[..., 2] = (a[..., 0] * alpha).astype(np.uint8)
        bgra[..., 3] = a[..., 3].astype(np.uint8)
        return np.ascontiguousarray(bgra)

    # -- 分层窗口
    def _ensure_dib(self, size):
        if self._dib and self._dib_size == size:
            return
        if self._memdc:
            gdi32.DeleteObject(self._dib)
            gdi32.DeleteDC(self._memdc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size          # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0          # BI_RGB
        bits = ctypes.c_void_p()
        self._dib = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0,
                                           ctypes.byref(bits), None, 0)
        self._dib_bits = bits
        self._memdc = gdi32.CreateCompatibleDC(None)
        gdi32.SelectObject(self._memdc, self._dib)
        self._dib_size = size

    def paint(self):
        size = self.size
        self._ensure_dib(size)
        buf = self.compose(size)
        ctypes.memmove(self._dib_bits, buf.ctypes.data, size * size * 4)
        bf = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        pt_dst = POINT(self.x, self.y)
        pt_src = POINT(0, 0)
        sz = SIZE(size, size)
        ok = user32.UpdateLayeredWindow(self._hwnd, self._screen_dc,
                                        ctypes.byref(pt_dst), ctypes.byref(sz),
                                        self._memdc, ctypes.byref(pt_src), 0,
                                        ctypes.byref(bf), ULW_ALPHA)
        if not ok:
            err = ctypes.get_last_error()
            if err:
                print("UpdateLayeredWindow failed:", err, file=sys.stderr)

    # -- 消息
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER:
            if self.paused:
                return 0
            try:
                self.paint()
            except Exception as exc:
                print("paint error:", exc, file=sys.stderr)
            return 0
        if msg == WM_LBUTTONDOWN:
            if self.locked:
                return 0
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._drag = (pt.x, pt.y, self.x, self.y)
            user32.SetCapture(hwnd)
            return 0
        if msg == WM_MOUSEMOVE and self._drag:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self.x = self._drag[2] + (pt.x - self._drag[0])
            self.y = self._drag[3] + (pt.y - self._drag[1])
            user32.SetWindowPos(hwnd, TOP, self.x, self.y, 0, 0,
                                SWP_NOSIZE | 0x0010)   # SWP_NOACTIVATE
            return 0
        if msg == WM_LBUTTONUP:
            self._drag = None
            user32.ReleaseCapture()
            self.save_cfg()
            return 0
        if msg == WM_MOUSEWHEEL:
            if self.locked:
                return 0
            delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            self.set_size(self.size + (20 if delta > 0 else -20))
            return 0
        if msg == WM_RBUTTONUP:
            self.show_menu(hwnd)
            return 0
        if msg == WM_KEYDOWN and wparam == VK_ESCAPE:
            self.shutdown()
            return 0
        if msg == WM_DESTROY:
            user32.KillTimer(hwnd, 1)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 右键菜单 ------------------------------------------------------
    def set_size(self, new_size):
        new_size = max(80, min(1600, int(new_size)))
        if new_size == self.size:
            return
        cx = self.x + self.size // 2
        cy = self.y + self.size // 2
        self.size = new_size
        self.x = cx - new_size // 2
        self.y = cy - new_size // 2
        if self._hwnd:
            user32.SetWindowPos(self._hwnd, TOP, self.x, self.y, 0, 0, SWP_NOSIZE | 0x0010)
        self.paint()
        self.save_cfg()

    def set_topmost(self, on):
        self.topmost = bool(on)
        if self._hwnd:
            user32.SetWindowPos(self._hwnd, TOP if self.topmost else HWND_NOTOPMOST,
                                self.x, self.y, 0, 0, SWP_NOSIZE | 0x0010)
        self.paint()

    def set_paused(self, on):
        self.paused = bool(on)
        if self.paused:
            self.frozen = self.src.get()
        else:
            self.frozen = None
        self.paint()

    def reconnect(self):
        """扔掉旧连接，重开读流线程（mjpeg / adb / jpeg-dir 三种源都支持）"""
        status = getattr(self.src, "status", "")
        kind = getattr(self, "source_kind", "mjpeg")
        self.src.stop()
        time.sleep(0.2)
        new_src = FrameSource()
        if kind == "adb":
            t = threading.Thread(target=adb_h264_reader,
                                 args=(new_src, self.args.adb, self.args.serial,
                                       self.args.ffmpeg, self.args.screen_size, self.args.crop),
                                 daemon=True)
            target = "adb screenrecord"
        elif kind == "jpeg-dir":
            t = threading.Thread(target=jpeg_dir_reader, args=(new_src, self.args.jpeg_dir), daemon=True)
            target = self.args.jpeg_dir
        else:
            url = self.args.url or "http://192.168.31.130:8088/video"
            t = threading.Thread(target=mjpeg_reader, args=(new_src, url), daemon=True)
            target = url
        t.start()
        self.src = new_src
        self.paused = False
        self.frozen = None
        print("reconnect(%s) -> %s (prev: %s)" % (kind, target, status), flush=True)

    # -- 退出：写退出标记（让 PC 端看门狗别再拉起来）+ 关掉手机摄像头 ----------
    def shutdown(self):
        self.save_cfg()
        flag = getattr(self.args, "exit_flag", "") or ""
        if flag:
            try:
                with open(flag, "w", encoding="utf-8") as fh:
                    fh.write(str(int(time.time())))
                print("exit flag -> %s" % flag, flush=True)
            except Exception as exc:
                print("exit flag failed: %s" % exc, file=sys.stderr)
        adb = getattr(self.args, "adb", "") or ""
        pkg = getattr(self.args, "stop_package", "") or ""
        if adb and pkg:
            try:
                cmd = [adb]
                serial = getattr(self.args, "serial", "") or ""
                if serial:
                    cmd += ["-s", serial]
                cmd += ["shell", "su -c 'am force-stop %s'" % pkg]
                subprocess.run(cmd, timeout=10)
                print("stopped phone camera: %s" % pkg, flush=True)
            except Exception as exc:
                print("stop phone camera failed: %s" % exc, file=sys.stderr)
        user32.PostQuitMessage(0)

    def show_menu(self, hwnd):
        ID_TOGGLE_PAUSE, ID_TOGGLE_LOCK, ID_TOGGLE_TOP = 1001, 1002, 1003
        ID_MIRROR, ID_RECONNECT, ID_QUIT = 1020, 1030, 1099
        ID_SIZE_BASE = 1200

        menu = user32.CreatePopupMenu()
        sub = user32.CreatePopupMenu()
        sizes = [200, 260, 320, 380, 460, 560, 700]
        for i, s in enumerate(sizes):
            flags = MF_STRING | (MF_CHECKED if abs(self.size - s) < 10 else 0)
            user32.AppendMenuW(sub, flags, ID_SIZE_BASE + i, "%d px" % s)
        user32.AppendMenuW(sub, MF_STRING, ID_SIZE_BASE + 90, "放大 40px")
        user32.AppendMenuW(sub, MF_STRING, ID_SIZE_BASE + 91, "缩小 40px")

        user32.AppendMenuW(menu, MF_STRING, ID_TOGGLE_PAUSE, "暂停画面" if not self.paused else "继续画面")
        user32.AppendMenuW(menu, MF_STRING, ID_TOGGLE_LOCK,
                           "固定位置大小" if not self.locked else "解除固定")
        user32.AppendMenuW(menu, MF_STRING, ID_TOGGLE_TOP,
                           "取消置顶" if self.topmost else "恢复置顶")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_POPUP, int(sub) if not hasattr(sub, "value") else int(sub.value), "画面大小")
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if self.mirror else 0), ID_MIRROR, "镜像画面")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_RECONNECT, "重新连接摄像头")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出（并关掉手机摄像头）")

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        flags = TPM_RETURNCMD | TPM_RIGHTBUTTON
        # 靠近屏幕右/下边缘时换对齐方式，免得菜单被挤出屏幕
        if pt.x > sw // 2:
            flags |= TPM_RIGHTALIGN
        if pt.y > sh // 2:
            flags |= TPM_BOTTOMALIGN
        cmd = user32.TrackPopupMenu(menu, flags, pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
        user32.PostMessageW(hwnd, 0, 0, 0)   # 让菜单关掉后马上回到我们的消息循环

        if not cmd:
            return
        if cmd == ID_TOGGLE_PAUSE:
            self.set_paused(not self.paused)
        elif cmd == ID_TOGGLE_LOCK:
            self.locked = not self.locked
            self.set_size(self.size)          # 触发重绘（描边颜色变化）
        elif cmd == ID_TOGGLE_TOP:
            self.set_topmost(not self.topmost)
        elif cmd == ID_MIRROR:
            self.mirror = not self.mirror
            self.paint()
        elif cmd == ID_RECONNECT:
            self.reconnect()
        elif cmd == ID_QUIT:
            self.shutdown()
        elif ID_SIZE_BASE <= cmd < ID_SIZE_BASE + 90:
            self.set_size(sizes[cmd - ID_SIZE_BASE])
        elif cmd == ID_SIZE_BASE + 90:
            self.set_size(self.size + 40)
        elif cmd == ID_SIZE_BASE + 91:
            self.set_size(self.size - 40)

    def run(self):
        # 逐显示器 DPI 感知（否则 Windows 会缩放我们的位图，圆会糊、尺寸对不上）
        aware = False
        try:
            u = ctypes.windll.user32
            u.SetProcessDpiAwarenessContext.restype = wt.BOOL
            u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            aware = bool(u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))  # PER_MONITOR_AWARE_V2
        except Exception:
            aware = False
        if not aware:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
                aware = True
            except Exception:
                try:
                    aware = bool(user32.SetProcessDPIAware())
                except Exception:
                    pass

        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.lpszClassName = "CamBubbleWnd"
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err not in (1410, 0):     # ERROR_CLASS_ALREADY_EXISTS
                raise ctypes.WinError(err)

        self._screen_dc = user32.GetDC(None)
        style_ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self._hwnd = user32.CreateWindowExW(style_ex, "CamBubbleWnd", "CamBubble",
                                            WS_POPUP | WS_VISIBLE,
                                            self.x, self.y, self.size, self.size,
                                            None, None, hinst, None)
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        user32.SetWindowPos(self._hwnd, TOP, self.x, self.y, 0, 0,
                            SWP_NOSIZE | 0x0010)
        user32.SetTimer(self._hwnd, 1, 33, None)
        user32.ShowWindow(self._hwnd, 5)  # SW_SHOW

        print("hwnd=0x%X size=%d pos=(%d,%d) topmost=yes" %
              (self._hwnd, self.size, self.x, self.y), flush=True)

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "test", "mjpeg", "adb", "jpeg-dir"],
                    default="auto", help="画面来源")
    ap.add_argument("--url", default="", help="MJPEG 流地址，如 http://192.168.31.130:4747/video")
    ap.add_argument("--test", action="store_true", help="本地合成画面自检")
    ap.add_argument("--jpeg-dir", default="", help="轮询目录里最新的 jpg")
    ap.add_argument("--adb", default="", help="adb.exe 路径（--source adb 用）")
    ap.add_argument("--serial", default="", help="adb 设备序列号/IP:PORT")
    ap.add_argument("--ffmpeg", default="", help="ffmpeg.exe 路径（--source adb 用）")
    ap.add_argument("--screen-size", default="720x1560", help="screenrecord 采集分辨率")
    ap.add_argument("--crop", default="", help="裁剪 WxH+X+Y；缺省取正中正方形")
    ap.add_argument("--size", type=int, default=320, help="圆形直径（px）")
    ap.add_argument("--x", type=int, default=-40, help="窗口左上角 X（负数=右对齐）")
    ap.add_argument("--y", type=int, default=-40, help="窗口左上角 Y（负数=底对齐）")
    ap.add_argument("--border", type=float, default=3.0, help="白圈宽度，0=无")
    ap.add_argument("--mirror", dest="mirror", action="store_true", default=True)
    ap.add_argument("--no-mirror", dest="mirror", action="store_false")
    ap.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--config", default="", help="保存 size/位置的 json")
    ap.add_argument("--seconds", type=float, default=0, help="N 秒后自动退出（自检用）")
    ap.add_argument("--exit-flag", default="", help="退出时写这个文件，PC 端看门狗据此不再重启")
    ap.add_argument("--stop-package", default="", help="退出时要 force-stop 的手机包名")
    args = ap.parse_args()

    src = FrameSource()
    source = args.source
    if args.test:
        source = "test"
    if source == "auto":
        if args.adb and args.ffmpeg:
            source = "adb"
        elif args.url:
            source = "mjpeg"
        else:
            source = "test"

    if source == "test":
        t = threading.Thread(target=test_reader, args=(src,), daemon=True)
    elif source == "adb":
        if not (args.adb and args.ffmpeg):
            sys.exit("--source adb 需要同时给 --adb 和 --ffmpeg")
        t = threading.Thread(target=adb_h264_reader,
                             args=(src, args.adb, args.serial, args.ffmpeg,
                                   args.screen_size, args.crop), daemon=True)
    elif source == "mjpeg":
        url = args.url or "http://192.168.31.130:4747/video"
        t = threading.Thread(target=mjpeg_reader, args=(src, url), daemon=True)
    else:
        t = threading.Thread(target=jpeg_dir_reader, args=(src, args.jpeg_dir), daemon=True)
    t.start()
    print("source=%s" % source, flush=True)

    app = Bubble(args, src)
    app.source_kind = source
    app.load_cfg()

    # 负数坐标 = 相对屏幕右下角（-40 表示离右/下边 40px）
    if args.x < 0:
        app.x = user32.GetSystemMetrics(0) - app.size + args.x
        app.y = user32.GetSystemMetrics(1) - app.size + args.y if args.y < 0 else app.y
    elif args.y < 0:
        app.y = user32.GetSystemMetrics(1) - app.size + args.y

    # 不管从哪来的坐标，一律夹到屏幕内（配置文件可能存过屏幕外的位置）
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    app.x = max(0, min(app.x, sw - app.size))
    app.y = max(0, min(app.y, sh - app.size))

    if args.seconds:
        threading.Timer(args.seconds, lambda: user32.PostQuitMessage(0)).start()

    app.run()
    src.stop()
    app.save_cfg()


if __name__ == "__main__":
    main()
