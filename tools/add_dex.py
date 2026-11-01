# -*- coding: utf-8 -*-
"""把 classes.dex 塞进 aapt2 产出的基础 apk 里。用法: add_dex.py base.apk classes.dex out.apk"""
import shutil
import sys
import zipfile

src, dex, out = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copyfile(src, out)
with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
    z.write(dex, "classes.dex")
print("added classes.dex ->", out)
