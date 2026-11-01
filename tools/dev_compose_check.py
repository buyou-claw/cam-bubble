# -*- coding: utf-8 -*-
"""离线检查 compose() 出来的 BGRA 是否正确（alpha 圆、颜色通道顺序）"""
import sys, time, threading
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\ai_project\redmik20")
import cam_bubble as cb

src = cb.FrameSource()
threading.Thread(target=cb.test_reader, args=(src,), daemon=True).start()
time.sleep(0.4)


class A:
    border = 3.0
    rotation = 0
    mirror = True
    size = 300
    x = 100
    y = 100
    config = ""


b = cb.Bubble(A(), src)
buf = b.compose(300)
print("shape", buf.shape)
print("alpha min/max", buf[..., 3].min(), buf[..., 3].max())
print("corner alpha", buf[0, 0, 3], "center alpha", buf[150, 150, 3])
print("center BGRA", buf[150, 150])
print("top-mid", buf[5, 150], "left-mid", buf[150, 5])
img = Image.fromarray(np.dstack([buf[..., 2], buf[..., 1], buf[..., 0]]))
img.save(r"E:\ai_project\redmik20\evidence\compose_check.png")

# 直接在纯色背景上合成，看看圆是不是完整的
bg = Image.new("RGB", (300, 300), (255, 255, 255))
rgba = Image.fromarray(np.dstack([buf[..., 2], buf[..., 1], buf[..., 0], buf[..., 3]]), "RGBA")
bg.paste(rgba, (0, 0), rgba)
bg.save(r"E:\ai_project\redmik20\evidence\compose_on_white.png")
print("saved")
