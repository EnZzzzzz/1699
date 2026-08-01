#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 cookies 表中所有代理出口 IP（非 direct）名下的 Cookie 记录。

背景：旧逻辑把 .cache/cookies_1688.json 里的匿名身份标识
（cookie2 / t / cna / _tb_token_ 等）播种给了每一个出口 IP，
导致同一套匿名身份出现在 100+ 个 IP 上，被风控标记（Cookie 重放）。
新逻辑下代理模式新出口 IP 一律空会话启动、由站点现场签发身份；
本脚本清掉历史污染记录，让轮换回来的旧 IP 复访时也走全新身份。

直连模式（identity='direct'）的记录保留不动。

用法:
    python3 scraper/taobao_1688/clean_proxy_cookies.py          # 先备份再清理
    python3 scraper/taobao_1688/clean_proxy_cookies.py --yes    # 跳过确认
"""

import shutil
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DB_PATH = ROOT_DIR / ".cache" / "1688.db"

sys.path.insert(0, str(BASE_DIR))
from database import ShopDB  # noqa: E402


def main() -> int:
    if not DB_PATH.exists():
        print(f"[X] 数据库不存在: {DB_PATH}")
        return 1

    db = ShopDB()
    rows = db.conn.execute(
        "SELECT identity, COUNT(*) AS n FROM cookies "
        "WHERE identity != 'direct' GROUP BY identity").fetchall()
    total = sum(r["n"] for r in rows)
    if not rows:
        print("[OK] 没有需要清理的代理 identity Cookie 记录")
        db.close()
        return 0

    print(f"[1] 待清理: {len(rows)} 个代理 identity，共 {total} 条 Cookie 记录")
    keep = db.conn.execute(
        "SELECT COUNT(*) FROM cookies WHERE identity='direct'").fetchone()[0]
    print(f"    保留: identity='direct' 的 {keep} 条记录")

    if "--yes" not in sys.argv:
        ans = input("[2] 确认清理？会先备份数据库到 .cache/backup/ [y/N] ")
        if ans.strip().lower() != "y":
            print("已取消")
            db.close()
            return 0

    backup_dir = ROOT_DIR / ".cache" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"1688_{time.strftime('%Y%m%d_%H%M%S')}.db"
    db.close()  # 先关连接再复制，保证文件一致
    shutil.copy2(DB_PATH, backup)
    print(f"[3] 已备份: {backup}")

    db = ShopDB()
    cur = db.conn.execute("DELETE FROM cookies WHERE identity != 'direct'")
    db.conn.commit()
    print(f"[OK] 已删除 {cur.rowcount} 条代理 identity Cookie 记录"
          f"（涉及 {len(rows)} 个出口 IP）")
    left = db.conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
    print(f"    cookies 表现剩 {left} 条（应全部为 direct）")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
