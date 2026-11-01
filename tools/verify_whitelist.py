# -*- coding: utf-8 -*-
"""复核手机上数据库里的白名单是否还在。"""
import sqlite3

BASE = r"E:\ai_project\redmik20\evidence\miui"

checks = [
    ("verify_pk.db", "SELECT pkgName,bgControl FROM userTable WHERE pkgName='dev.local.camstream'"),
    ("verify_wake.db", "SELECT PkgName,userSettings FROM WakePathWhiteList"),
]
for name, sql in checks:
    path = (BASE + "\\" + name).replace("\\", "/")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        print("%-16s %s" % (name, con.execute(sql).fetchall()))
    finally:
        con.close()
