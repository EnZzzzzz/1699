# -*- coding: utf-8 -*-
"""Step 2.1 _migrate() cookies 表前缀迁移单测。

TDD: 先写测试 → 看到 RED → 实现 _migrate → GREEN。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fetcher.db import SCHEMA, ShopDB
from fetcher import IdentityStore


NOW_TS = 1700000000


def _cookie_row(identity, name="cna", value="v", domain=".1688.com",
                path="/", secure=0, http_only=0, expires=None,
                updated_at="2025-08-08 00:00:00"):
    """返回 (identity, name, value, domain, path, secure, http_only,
    expires, updated_at) 元组。"""
    return (identity, name, value, domain, path, secure, http_only,
            expires, updated_at)


class CookiesMigrationTest(unittest.TestCase):
    """SPEC §5.4: _migrate() 幂等前缀迁移。

    测试流程：
    1. 手工建库 + 插旧格式裸键行
    2. ShopDB() 打开触发 _migrate()
    3. 断言迁移结果
    4. 再迁移零变化（幂等）
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _insert_raw_cookies(self):
        """用裸 sqlite3 手工建表 + 插入旧格式行（不触发 _migrate）。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        # 插入旧格式行（全部裸键，无 site: 前缀）
        rows = [
            # 1688 域 ×3，identity = 1.2.3.4
            ("1.2.3.4", "cna", "v1", ".1688.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            ("1.2.3.4", "cookie2", "v2", "insights.1688.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            ("1.2.3.4", "x5sec", "v3", "s.1688.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            # made-in-china 域 ×2，identity = 5.5.5.5
            ("5.5.5.5", "cna", "v4", ".made-in-china.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            ("5.5.5.5", "q", "v5", "cn.made-in-china.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            # taobao 域 ×1，identity = 6.6.6.6
            ("6.6.6.6", "_tb_", "v6", ".taobao.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            # yiwugo 域 ×1，identity = 7.7.7.7
            ("7.7.7.7", "cna", "v7", ".yiwugo.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
            # mmstat 第三方域 ×1，identity = 8.8.8.8（无法映射，应保持裸键）
            ("8.8.8.8", "cna", "v8", ".mmstat.com", "/", 0, 0, None,
             "2025-08-08 00:00:00"),
        ]
        conn.executemany(
            "INSERT INTO cookies (identity, name, value, domain, path,"
            " secure, http_only, expires, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

    def _snapshot_cookies(self, db):
        """返回 cookies 表 (identity, domain, name) 全量快照的
        frozenset，用于幂等断言。"""
        rows = db.conn.execute(
            "SELECT identity, domain, name FROM cookies"
            " ORDER BY id").fetchall()
        return frozenset((r["identity"], r["domain"], r["name"]) for r in rows)

    def _bare_count(self, db):
        """返回 identity NOT LIKE '%:%' 的行数。"""
        return db.conn.execute(
            "SELECT COUNT(*) FROM cookies WHERE identity NOT LIKE '%:%'"
        ).fetchone()[0]

    # ---- 迁移主流程 ----

    def test_migration_prefixes_bare_identities(self):
        """迁移：裸键按 cookie domain 映射加 site: 前缀。

        RED 预期：_migrate() 未实现 → 打开库后 identity 仍为裸键
        → 断言 "1688:1.2.3.4" 行数为 0 → 失败。
        """
        self._insert_raw_cookies()
        db = ShopDB(self.db_path)

        # 验证每个映射
        def count(identity):
            return db.conn.execute(
                "SELECT COUNT(*) FROM cookies WHERE identity=?",
                (identity,)).fetchone()[0]

        # 1688 域行 → 1688:1.2.3.4
        self.assertEqual(count("1688:1.2.3.4"), 3,
                         "1688 域 3 行应迁移为 1688:1.2.3.4")
        # made-in-china 域 → madeinchina:5.5.5.5
        self.assertEqual(count("madeinchina:5.5.5.5"), 2,
                         "made-in-china 域 2 行应迁移为 madeinchina:5.5.5.5")
        # taobao 域 → taobao:6.6.6.6
        self.assertEqual(count("taobao:6.6.6.6"), 1,
                         "taobao 域应迁移为 taobao:6.6.6.6")
        # yiwugo 域 → yiwugo:7.7.7.7
        self.assertEqual(count("yiwugo:7.7.7.7"), 1,
                         "yiwugo 域应迁移为 yiwugo:7.7.7.7")
        # mmstat 第三方域保持裸键
        self.assertEqual(count("8.8.8.8"), 1,
                         "mmstat 第三方域应保持裸键")

        db.close()

    def test_load_after_migration(self):
        """迁移后 1688 Cookie 可被新键正常 load（SPEC §5.4）。"""
        self._insert_raw_cookies()
        db = ShopDB(self.db_path)
        store = IdentityStore(db, domain="1688.com")
        loaded = store.load("1688:1.2.3.4")
        names = {c["name"] for c in loaded}
        self.assertEqual(names, {"cna", "cookie2", "x5sec"},
                         f"迁移后应能 load 到 3 个 1688 Cookie，实际={names}")
        db.close()

    def test_migration_idempotent(self):
        """再迁移零变化：重开库后全表快照逐行一致。

        RED 预期：_migrate() 未实现 → 快照不变是无意义的
        （identity 都是裸键），但至少证明幂等框架是对的。
        实现后：第一次打开迁移 → 第二次打开不变 → 快照相等。
        """
        self._insert_raw_cookies()
        # 第一次打开：触发迁移
        db1 = ShopDB(self.db_path)
        snap1 = self._snapshot_cookies(db1)
        bare1 = self._bare_count(db1)
        db1.close()

        # 第二次打开：再迁移应零变化
        db2 = ShopDB(self.db_path)
        snap2 = self._snapshot_cookies(db2)
        bare2 = self._bare_count(db2)
        db2.close()

        self.assertEqual(snap1, snap2,
                        f"再迁移后快照应完全一致")
        # 裸键只含 mmstat 行（identity=8.8.8.8）
        self.assertEqual(bare1, 1,
                        f"迁移后裸键应为 1（mmstat），实际={bare1}")
        self.assertEqual(bare2, 1,
                        f"再迁移后裸键仍为 1，实际={bare2}")

    def test_migration_skips_prefixed(self):
        """已带前缀的 identity 不被重复迁移（幂等性单元验证）。"""
        self._insert_raw_cookies()
        # 手工加一条已迁移过的格式
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO cookies (identity, name, value, domain, path,"
            " secure, http_only, expires, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("1688:9.9.9.9", "prefixed", "v", ".1688.com", "/",
             0, 0, None, "2025-08-08 00:00:00"))
        conn.commit()
        conn.close()

        db = ShopDB(self.db_path)

        def count(identity):
            return db.conn.execute(
                "SELECT COUNT(*) FROM cookies WHERE identity=?",
                (identity,)).fetchone()[0]

        # 原有裸键已迁移
        self.assertEqual(count("1688:1.2.3.4"), 3)
        # 已带前缀的不动
        self.assertEqual(count("1688:9.9.9.9"), 1)
        # 不应有两条 1688: 前缀叠加
        self.assertEqual(count("1688:1688:9.9.9.9"), 0)

        db.close()


if __name__ == "__main__":
    unittest.main()
