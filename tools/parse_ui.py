# -*- coding: utf-8 -*-
"""解析 uiautomator 的 ui.xml，打印带文字/描述的控件中心坐标。用法: parse_ui.py file.xml [过滤词]"""
import re
import sys

path = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else ""

raw = open(path, encoding="utf-8", errors="replace").read()
count = 0
for m in re.finditer(r"<node[^>]*>", raw):
    t = m.group(0)
    d = re.search(r'content-desc="([^"]*)"', t)
    tx = re.search(r'text="([^"]*)"', t)
    b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', t)
    if not b:
        continue
    desc = d.group(1) if d else ""
    text = tx.group(1) if tx else ""
    label = (text + "|" + desc).strip("|")
    if not label:
        continue
    if needle and needle not in label:
        continue
    x = (int(b.group(1)) + int(b.group(3))) // 2
    y = (int(b.group(2)) + int(b.group(4))) // 2
    click = "CLICK" if 'clickable="true"' in t else ""
    print("%-26s (%4d,%4d) %sx%s %s" % (label[:26], x, y,
                                        int(b.group(3)) - int(b.group(1)),
                                        int(b.group(4)) - int(b.group(2)), click))
    count += 1
print("-- total", count, "nodes")
