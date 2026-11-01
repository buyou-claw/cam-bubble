# -*- coding: utf-8 -*-
"""读 MJPEG 流 N 秒，统计帧率和分辨率，证明「实时」不是一张卡住的图。"""
import io
import sys
import time
import urllib.request

from PIL import Image

url = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.31.130:8088/video"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

t0 = time.time()
frames = 0
times = []
buf = b""
size = None
with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "probe"}), timeout=10) as r:
    print("content-type:", r.headers.get("Content-Type"))
    while time.time() - t0 < secs:
        chunk = r.read(16384)
        if not chunk:
            break
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
            if s >= 0 and e > s:
                jpg = buf[s:e + 2]
                buf = buf[e + 2:]
                frames += 1
                times.append(time.time() - t0)
                if size is None:
                    im = Image.open(io.BytesIO(jpg))
                    size = im.size
            else:
                break

elapsed = time.time() - t0
print("frames=%d  elapsed=%.2fs  fps=%.1f  first_frame_at=%.3fs  size=%s" %
      (frames, elapsed, frames / elapsed if elapsed else 0,
       times[0] if times else -1, size))
