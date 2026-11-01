# -*- coding: utf-8 -*-
"""看一眼 MIUI 的 powerkeeper / lbe 数据库里都存了什么（只读）。"""
import sqlite3
import sys

for path in sys.argv[1:]:
    print("=" * 70)
    print(path)
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cur = con.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for name, sql in cur.fetchall():
        print("-- table:", name)
        print("   ", (sql or "").replace("\n", " ")[:300])
    for (name,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        try:
            rows = cur.execute("SELECT * FROM '%s' LIMIT 8" % name).fetchall()
            cols = [d[0] for d in cur.description]
            print("   [%s] cols=%s rows=%d" % (name, cols, len(rows)))
            for r in rows[:6]:
                print("      ", [str(v)[:40] for v in r])
        except Exception as exc:
            print("   !!", name, exc)
    con.close()
