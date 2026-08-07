# Step 3.1 种子脚本：生产库只读抄 6 条真实 1688 店铺 → 两个临时库（status='pending'，同序）
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "fetcher"))
from fetcher.db import ShopDB  # noqa: E402

PROD = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"
TARGETS = ["/tmp/cooldown_a.db", "/tmp/cooldown_b.db"]

src = sqlite3.connect(f"file:{PROD}?mode=ro", uri=True)
src.row_factory = sqlite3.Row
rows = src.execute(
    """SELECT domain, name, url, category_keyword, first_seen_at, last_seen_at
       FROM shops WHERE status='done' AND domain LIKE '%.1688.com'
       ORDER BY id DESC LIMIT 6"""
).fetchall()
assert len(rows) == 6, f"候选不足: {len(rows)}"
src.close()

for path in TARGETS:
    for suffix in ("", "-wal", "-shm"):
        Path(path + suffix).unlink(missing_ok=True)
    db = ShopDB(path)  # 建 schema（WAL + 幂等迁移）
    for r in rows:
        db.conn.execute(
            """INSERT INTO shops (domain, name, url, category_keyword, run_id,
                                  first_seen_at, last_seen_at, status, attempts)
               VALUES (?,?,?,?,NULL,?,?,'pending',0)""",
            (r["domain"], r["name"], r["url"], r["category_keyword"],
             r["first_seen_at"], r["last_seen_at"]),
        )
    db.conn.commit()
    n = db.conn.execute("SELECT COUNT(*) FROM shops WHERE status='pending'").fetchone()[0]
    first = db.conn.execute(
        "SELECT domain FROM shops WHERE status='pending' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    print(f"{path}: pending={n}, 首个待认领={first}")
    db.conn.close()

# 种子清单留档（smoke/ 下）
out = Path(__file__).with_name("seed_list.txt")
out.write_text("\n".join(f"{r['domain']}\t{r['name']}" for r in rows) + "\n")
print(f"种子清单 → {out}")
