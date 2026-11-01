# -*- coding: utf-8 -*-
"""给某个包写 MIUI 白名单：省电策略=无限制、自启动=允许。

流程（全部离线改 PC 侧副本，再推回手机）：
  1. 手机上以 root 把两个库拷到 /data/local/tmp（因为 /data/data 下 shell 读不了）
  2. adb pull 到 build/miui/
  3. 本地 sqlite3 改两行
  4. 打印/执行推回命令

前提：手机已 root，`adb shell su -c id` 返回 uid=0。

用法：
  python tools/miui_whitelist.py --pull                 # 只把库拉到 build/miui/
  python tools/miui_whitelist.py                        # 改库，打印推回命令
  python tools/miui_whitelist.py --push                 # 改库并推回（会停 MIUI 那两个服务）

默认包名 dev.local.camstream，可用 --package 改。
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time

PK_DB = "/data/data/com.miui.powerkeeper/databases/user_configure.db"
WAKE_DB = "/data/data/com.lbe.security.miui/databases/wake_path.db"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ADB = os.path.join(ROOT, "tools", "scrcpy-win64-v5.0.1", "adb.exe")


def run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def pick_serial(adb_exe):
    """多设备时自动挑一个（优先 USB 序列号，其次 IP:PORT）"""
    out = run([adb_exe, "devices"]).stdout
    devs = [l.split("\t")[0] for l in out.splitlines() if l.endswith("\tdevice")]
    if not devs:
        raise RuntimeError("没有在线的 adb 设备")
    devs.sort(key=lambda d: (":" in d, d))     # 不带冒号的（USB 序列号）排前面
    return devs[0]


def adb(args, adb_exe, serial):
    if not serial:
        serial = pick_serial(adb_exe)
    cmd = [adb_exe] + (["-s", serial] if serial else []) + args
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("%s\n%s" % (" ".join(cmd), (r.stderr or r.stdout).strip()))
    return r.stdout


def pull(adb_exe, serial, workdir):
    os.makedirs(workdir, exist_ok=True)
    adb(["shell", "su -c 'cp %s /data/local/tmp/pk_user.db; cp %s /data/local/tmp/lbe_wake.db; "
         "chmod 666 /data/local/tmp/pk_user.db /data/local/tmp/lbe_wake.db'" % (PK_DB, WAKE_DB)],
        adb_exe, serial)
    for remote, local in (("pk_user.db", "pk_user.db"), ("lbe_wake.db", "lbe_wake.db")):
        adb(["pull", "/data/local/tmp/" + remote, os.path.join(workdir, local)], adb_exe, serial)
    print("pulled ->", workdir)


def patch(workdir, pkg):
    src_pk = os.path.join(workdir, "pk_user.db")
    src_wake = os.path.join(workdir, "lbe_wake.db")
    dst_pk = os.path.join(workdir, "pk_user_mod.db")
    dst_wake = os.path.join(workdir, "lbe_wake_mod.db")
    shutil.copyfile(src_pk, dst_pk)
    shutil.copyfile(src_wake, dst_wake)

    now = int(time.time() * 1000)
    con = sqlite3.connect(dst_pk)
    row = con.execute("SELECT _id, bgControl FROM userTable WHERE userId=0 AND pkgName=?", (pkg,)).fetchone()
    if row:
        con.execute("UPDATE userTable SET bgControl='noRestrict', lastConfigured=? "
                    "WHERE userId=0 AND pkgName=?", (now, pkg))
        print("powerkeeper: %s  %s -> noRestrict" % (pkg, row[1]))
    else:
        con.execute("INSERT INTO userTable (userId,pkgName,lastConfigured,bgControl,bgLocation,bgDelayMin) "
                    "VALUES (0,?,?,'noRestrict','None','None')", (pkg, now))
        print("powerkeeper: %s  新增 -> noRestrict" % pkg)
    con.commit()
    con.close()

    con = sqlite3.connect(dst_wake)
    con.execute("DELETE FROM WakePathWhiteList WHERE PkgName=?", (pkg,))
    con.execute("INSERT INTO WakePathWhiteList (PkgName,userSettings) VALUES (?,1)", (pkg,))
    con.commit()
    con.close()
    print("lbe wake : %s  自启动=允许(userSettings=1)" % pkg)


def push(adb_exe, serial, workdir):
    for name in ("pk_user_mod.db", "lbe_wake_mod.db"):
        adb(["push", os.path.join(workdir, name), "/data/local/tmp/" + name], adb_exe, serial)
    adb(["push", os.path.join(ROOT, "scripts", "apply_miui_whitelist.sh"),
         "/data/local/tmp/apply_miui_whitelist.sh"], adb_exe, serial)
    out = adb(["shell", "su -c 'sh /data/local/tmp/apply_miui_whitelist.sh'"], adb_exe, serial)
    print(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default=DEFAULT_ADB)
    ap.add_argument("--serial", default="")
    ap.add_argument("--package", default="dev.local.camstream")
    ap.add_argument("--dir", default=os.path.join(ROOT, "build", "miui"))
    ap.add_argument("--pull", action="store_true", help="只拉库")
    ap.add_argument("--push", action="store_true", help="改完推回手机")
    args = ap.parse_args()

    if not os.path.exists(args.adb):
        sys.exit("找不到 adb: %s" % args.adb)

    pull(args.adb, args.serial, args.dir)
    if args.pull:
        return
    patch(args.dir, args.package)
    if args.push:
        push(args.adb, args.serial, args.dir)
    else:
        print("\n改好的库在 %s，推回手机执行：" % args.dir)
        print("  python tools/miui_whitelist.py --push")


if __name__ == "__main__":
    main()
