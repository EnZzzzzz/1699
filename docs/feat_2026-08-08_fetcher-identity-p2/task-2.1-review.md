# Step 2.1 review 审查包（BASE dd6dea5..HEAD a7ee816）

## git log
a7ee816 feat(identity-p2): Step 2.1 Session.close 域过滤 + _migrate 前缀迁移

## git diff --stat
 fetcher/fetcher/core/session.py |   5 +-
 fetcher/fetcher/db.py           |  20 ++++
 fetcher/tests/test_identity.py  |  95 +++++++++++++++++++
 fetcher/tests/test_migration.py | 202 ++++++++++++++++++++++++++++++++++++++++
 4 files changed, 321 insertions(+), 1 deletion(-)

## git diff -U10
diff --git a/fetcher/fetcher/core/session.py b/fetcher/fetcher/core/session.py
index 2c2f477..c97f275 100644
--- a/fetcher/fetcher/core/session.py
+++ b/fetcher/fetcher/core/session.py
@@ -58,21 +58,24 @@ class Session:
         return self.channel is not None and self.channel.server is not None
 
     def close(self, store=None, log=None):
         """关闭会话：先回写 Cookie（给了 store 时），再关浏览器。
 
         任何退出路径都应走这里，保证服务端会话租约及时释放、
         Cookie 信任链不丢。
         """
         if store is not None and self.page is not None:
             try:
-                cookies = [c for c in self.ctx.cookies()]
+                # 多站共存：按 store.domain 过滤，保证桶纯度——
+                # 同 IP 两站点各存各桶，回写不串站（与 save_from_context 同语义）
+                cookies = [c for c in self.ctx.cookies()
+                           if getattr(store, "domain", "") in c.get("domain", "")]
                 if cookies:
                     store.save(self.identity, cookies)
             except Exception as e:  # noqa: BLE001 - 回写失败不阻断关闭
                 if log:
                     log(f"[!] 旧 Cookie 回写失败: {e}")
         if self.browser is not None:
             try:
                 self.browser.close()
             except Exception:  # noqa: BLE001
                 pass
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 6f1f978..7af8033 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -241,20 +241,40 @@ class ShopDB:
                WHERE status='done' AND id IN (
                    SELECT shop_id FROM contacts
                    WHERE contact_person IS NULL AND phone IS NULL
                      AND mobile IS NULL AND fax IS NULL AND address IS NULL)""")
         # ip_events 补 req_since_block 列（tmd 触发阈值样本：
         # 本次触发时距该 IP 上次触发已爬多少个页面请求）
         evt_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ip_events)")}
         if "req_since_block" not in evt_cols:
             self.conn.execute(
                 "ALTER TABLE ip_events ADD COLUMN req_since_block INTEGER")
+        # cookies 表裸键按 domain→site 映射加前缀（P2 identity 升级：
+        # identity 键从裸 IP 升级为 site:ip）。部署窗口：旧进程裸键读不到
+        # 新前缀 Cookie → 白板重启一次（SPEC §3.4 运维注意）。
+        # 映射清单（先长后短，SPEC §3.4 回填）：
+        self.conn.execute(
+            "UPDATE cookies SET identity = 'madeinchina:' || identity"
+            " WHERE identity NOT LIKE '%:%'"
+            " AND domain LIKE '%made-in-china.com%'")
+        self.conn.execute(
+            "UPDATE cookies SET identity = '1688:' || identity"
+            " WHERE identity NOT LIKE '%:%'"
+            " AND domain LIKE '%1688.com%'")
+        self.conn.execute(
+            "UPDATE cookies SET identity = 'taobao:' || identity"
+            " WHERE identity NOT LIKE '%:%'"
+            " AND domain LIKE '%taobao.com%'")
+        self.conn.execute(
+            "UPDATE cookies SET identity = 'yiwugo:' || identity"
+            " WHERE identity NOT LIKE '%:%'"
+            " AND domain LIKE '%yiwugo.com%'")
 
     # ---------- crawl_runs ----------
     def start_run(self, category_name: str = None,
                   category_keyword: str = None) -> int:
         cur = self.conn.execute(
             "INSERT INTO crawl_runs (started_at, category_name, category_keyword)"
             " VALUES (?, ?, ?)",
             (_now(), category_name, category_keyword))
         self.conn.commit()
         return cur.lastrowid
diff --git a/fetcher/tests/test_identity.py b/fetcher/tests/test_identity.py
index f8a8ee2..e0a27d6 100644
--- a/fetcher/tests/test_identity.py
+++ b/fetcher/tests/test_identity.py
@@ -1,19 +1,20 @@
 # -*- coding: utf-8 -*-
 """IdentityStore 单测：Cookie 按 identity 隔离、过期剔除、burn 清空。
 使用临时 sqlite 文件，不碰真实数据库。"""
 
 import tempfile
 import threading
 import time
 import unittest
 from pathlib import Path
+from unittest.mock import MagicMock
 
 from fetcher import IdentityStore, RunConfig, Session, ShopDB, WorkerContext
 from fetcher.atoms.identity_ops import ClearIdentity
 from fetcher.core.types import Outcome
 
 NOW = int(time.time())
 
 
 def ck(name, value="v", domain=".1688.com", expires=None):
     c = {"name": name, "value": value, "domain": domain, "path": "/",
@@ -242,12 +243,106 @@ class IdentityP2CompatibilityTest(unittest.TestCase):
             digit_pos = idx + len(ident) + len(after) - len(after.lstrip())
             positions[ident] = digit_pos
         # 修正后：两行的请求列应起始于同一列
         self.assertEqual(
             positions[ident_long], positions[ident_short],
             f"不同长度 identity 的请求列应对齐，实际 "
             f"{ident_short}={positions[ident_short]}, "
             f"{ident_long}={positions[ident_long]}")
 
 
+class SessionCloseDomainFilterTest(unittest.TestCase):
+    """Step 2.1: Session.close() 回写按 store.domain 过滤。
+
+    多站共存前提下的桶纯度保证——同 IP 两站点各存各桶，回写不串站。
+    """
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "test.db"
+        self.db = ShopDB(self.db_path)
+        self.store_1688 = IdentityStore(self.db, domain="1688.com")
+        self.store_mic = IdentityStore(self.db, domain="made-in-china.com")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_close_filters_cookies_by_store_domain_1688(self):
+        """Session.close: store.domain='1688.com' 时只存 1688 域 Cookie。
+
+        RED 预期：close() 不过滤 → 3 个 Cookie 全入库 →
+        load 返回 3 个 → 断言 len==1 失败。
+        """
+        ctx = FakeBrowserContext([
+            ck("cna", domain=".1688.com"),
+            ck("_tb_", domain=".taobao.com"),
+            ck("cna", domain=".mmstat.com"),
+        ])
+        page = MagicMock(context=ctx)
+        session = Session(browser=MagicMock(), page=page,
+                          identity="1688:1.2.3.4")
+        session.close(store=self.store_1688)
+        loaded = self.store_1688.load("1688:1.2.3.4")
+        self.assertEqual(len(loaded), 1,
+                         f"应只存 1688 域 Cookie，实际={loaded}")
+        self.assertEqual(loaded[0]["name"], "cna")
+
+    def test_close_filters_cookies_by_store_domain_mic(self):
+        """Session.close: store.domain='made-in-china.com' 时只存 mic 域。"""
+        ctx = FakeBrowserContext([
+            ck("cna", domain=".1688.com"),
+            ck("q", domain=".made-in-china.com"),
+            ck("cna", domain=".mmstat.com"),
+        ])
+        page = MagicMock(context=ctx)
+        session = Session(browser=MagicMock(), page=page,
+                          identity="madeinchina:5.5.5.5")
+        session.close(store=self.store_mic)
+        loaded = self.store_mic.load("madeinchina:5.5.5.5")
+        self.assertEqual(len(loaded), 1,
+                         f"应只存 mic 域 Cookie，实际={loaded}")
+        self.assertEqual(loaded[0]["name"], "q")
+
+    def test_close_store_none_no_write(self):
+        """Session.close: store=None 时不过滤、不回写。"""
+        ctx = FakeBrowserContext([ck("cna")])
+        page = MagicMock(context=ctx)
+        session = Session(browser=MagicMock(), page=page,
+                          identity="1.2.3.4")
+        session.close(store=None)  # 不应抛异常
+        self.assertEqual(self.store_1688.load("1.2.3.4"), [])
+
+    def test_close_page_none_no_write(self):
+        """Session.close: page=None 时跳过回写，不抛异常。"""
+        session = Session(browser=MagicMock(), page=None,
+                          identity="1.2.3.4")
+        session.close(store=self.store_1688)  # 不抛异常
+        self.assertEqual(self.store_1688.load("1.2.3.4"), [])
+
+    def test_close_no_domain_attr_passthrough(self):
+        """Session.close: store 无 domain 属性时，getattr 返回 ''
+        → '' in any_domain → 恒真 → 全量回写（与 save_from_context
+        语义对齐）。用 Mock 模拟非 IdentityStore 的 store。"""
+        ctx = FakeBrowserContext([
+            ck("cna", domain=".1688.com"),
+            ck("_tb_", domain=".taobao.com"),
+        ])
+        page = MagicMock(context=ctx)
+        # 构造不暴露 domain 属性的 store（实际调用方都是 IdentityStore，
+        # getattr 纯粹防御）
+        mock_store = MagicMock(save=MagicMock())
+        # 确保 mock_store 没有 domain 属性
+        del mock_store.domain
+        session = Session(browser=MagicMock(), page=page,
+                          identity="1.2.3.4")
+        session.close(store=mock_store)
+        mock_store.save.assert_called_once()
+        args, _ = mock_store.save.call_args
+        saved_identity, saved_cookies = args
+        self.assertEqual(saved_identity, "1.2.3.4")
+        self.assertEqual(len(saved_cookies), 2,
+                         f"无 domain 属性应全量回写，实际={saved_cookies}")
+
+
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_migration.py b/fetcher/tests/test_migration.py
new file mode 100644
index 0000000..a5a0dbc
--- /dev/null
+++ b/fetcher/tests/test_migration.py
@@ -0,0 +1,202 @@
+# -*- coding: utf-8 -*-
+"""Step 2.1 _migrate() cookies 表前缀迁移单测。
+
+TDD: 先写测试 → 看到 RED → 实现 _migrate → GREEN。
+"""
+
+import sqlite3
+import tempfile
+import unittest
+from pathlib import Path
+
+from fetcher.db import SCHEMA, ShopDB
+from fetcher import IdentityStore
+
+
+NOW_TS = 1700000000
+
+
+def _cookie_row(identity, name="cna", value="v", domain=".1688.com",
+                path="/", secure=0, http_only=0, expires=None,
+                updated_at="2025-08-08 00:00:00"):
+    """返回 (identity, name, value, domain, path, secure, http_only,
+    expires, updated_at) 元组。"""
+    return (identity, name, value, domain, path, secure, http_only,
+            expires, updated_at)
+
+
+class CookiesMigrationTest(unittest.TestCase):
+    """SPEC §5.4: _migrate() 幂等前缀迁移。
+
+    测试流程：
+    1. 手工建库 + 插旧格式裸键行
+    2. ShopDB() 打开触发 _migrate()
+    3. 断言迁移结果
+    4. 再迁移零变化（幂等）
+    """
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = str(Path(self._tmp.name) / "test.db")
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def _insert_raw_cookies(self):
+        """用裸 sqlite3 手工建表 + 插入旧格式行（不触发 _migrate）。"""
+        conn = sqlite3.connect(self.db_path)
+        conn.execute("PRAGMA journal_mode=WAL")
+        conn.executescript(SCHEMA)
+        # 插入旧格式行（全部裸键，无 site: 前缀）
+        rows = [
+            # 1688 域 ×3，identity = 1.2.3.4
+            ("1.2.3.4", "cna", "v1", ".1688.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            ("1.2.3.4", "cookie2", "v2", "insights.1688.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            ("1.2.3.4", "x5sec", "v3", "s.1688.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            # made-in-china 域 ×2，identity = 5.5.5.5
+            ("5.5.5.5", "cna", "v4", ".made-in-china.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            ("5.5.5.5", "q", "v5", "cn.made-in-china.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            # taobao 域 ×1，identity = 6.6.6.6
+            ("6.6.6.6", "_tb_", "v6", ".taobao.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            # yiwugo 域 ×1，identity = 7.7.7.7
+            ("7.7.7.7", "cna", "v7", ".yiwugo.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+            # mmstat 第三方域 ×1，identity = 8.8.8.8（无法映射，应保持裸键）
+            ("8.8.8.8", "cna", "v8", ".mmstat.com", "/", 0, 0, None,
+             "2025-08-08 00:00:00"),
+        ]
+        conn.executemany(
+            "INSERT INTO cookies (identity, name, value, domain, path,"
+            " secure, http_only, expires, updated_at)"
+            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
+        conn.commit()
+        conn.close()
+
+    def _snapshot_cookies(self, db):
+        """返回 cookies 表 (identity, domain, name) 全量快照的
+        frozenset，用于幂等断言。"""
+        rows = db.conn.execute(
+            "SELECT identity, domain, name FROM cookies"
+            " ORDER BY id").fetchall()
+        return frozenset((r["identity"], r["domain"], r["name"]) for r in rows)
+
+    def _bare_count(self, db):
+        """返回 identity NOT LIKE '%:%' 的行数。"""
+        return db.conn.execute(
+            "SELECT COUNT(*) FROM cookies WHERE identity NOT LIKE '%:%'"
+        ).fetchone()[0]
+
+    # ---- 迁移主流程 ----
+
+    def test_migration_prefixes_bare_identities(self):
+        """迁移：裸键按 cookie domain 映射加 site: 前缀。
+
+        RED 预期：_migrate() 未实现 → 打开库后 identity 仍为裸键
+        → 断言 "1688:1.2.3.4" 行数为 0 → 失败。
+        """
+        self._insert_raw_cookies()
+        db = ShopDB(self.db_path)
+
+        # 验证每个映射
+        def count(identity):
+            return db.conn.execute(
+                "SELECT COUNT(*) FROM cookies WHERE identity=?",
+                (identity,)).fetchone()[0]
+
+        # 1688 域行 → 1688:1.2.3.4
+        self.assertEqual(count("1688:1.2.3.4"), 3,
+                         "1688 域 3 行应迁移为 1688:1.2.3.4")
+        # made-in-china 域 → madeinchina:5.5.5.5
+        self.assertEqual(count("madeinchina:5.5.5.5"), 2,
+                         "made-in-china 域 2 行应迁移为 madeinchina:5.5.5.5")
+        # taobao 域 → taobao:6.6.6.6
+        self.assertEqual(count("taobao:6.6.6.6"), 1,
+                         "taobao 域应迁移为 taobao:6.6.6.6")
+        # yiwugo 域 → yiwugo:7.7.7.7
+        self.assertEqual(count("yiwugo:7.7.7.7"), 1,
+                         "yiwugo 域应迁移为 yiwugo:7.7.7.7")
+        # mmstat 第三方域保持裸键
+        self.assertEqual(count("8.8.8.8"), 1,
+                         "mmstat 第三方域应保持裸键")
+
+        db.close()
+
+    def test_load_after_migration(self):
+        """迁移后 1688 Cookie 可被新键正常 load（SPEC §5.4）。"""
+        self._insert_raw_cookies()
+        db = ShopDB(self.db_path)
+        store = IdentityStore(db, domain="1688.com")
+        loaded = store.load("1688:1.2.3.4")
+        names = {c["name"] for c in loaded}
+        self.assertEqual(names, {"cna", "cookie2", "x5sec"},
+                         f"迁移后应能 load 到 3 个 1688 Cookie，实际={names}")
+        db.close()
+
+    def test_migration_idempotent(self):
+        """再迁移零变化：重开库后全表快照逐行一致。
+
+        RED 预期：_migrate() 未实现 → 快照不变是无意义的
+        （identity 都是裸键），但至少证明幂等框架是对的。
+        实现后：第一次打开迁移 → 第二次打开不变 → 快照相等。
+        """
+        self._insert_raw_cookies()
+        # 第一次打开：触发迁移
+        db1 = ShopDB(self.db_path)
+        snap1 = self._snapshot_cookies(db1)
+        bare1 = self._bare_count(db1)
+        db1.close()
+
+        # 第二次打开：再迁移应零变化
+        db2 = ShopDB(self.db_path)
+        snap2 = self._snapshot_cookies(db2)
+        bare2 = self._bare_count(db2)
+        db2.close()
+
+        self.assertEqual(snap1, snap2,
+                        f"再迁移后快照应完全一致")
+        # 裸键只含 mmstat 行（identity=8.8.8.8）
+        self.assertEqual(bare1, 1,
+                        f"迁移后裸键应为 1（mmstat），实际={bare1}")
+        self.assertEqual(bare2, 1,
+                        f"再迁移后裸键仍为 1，实际={bare2}")
+
+    def test_migration_skips_prefixed(self):
+        """已带前缀的 identity 不被重复迁移（幂等性单元验证）。"""
+        self._insert_raw_cookies()
+        # 手工加一条已迁移过的格式
+        conn = sqlite3.connect(self.db_path)
+        conn.execute("PRAGMA journal_mode=WAL")
+        conn.execute(
+            "INSERT INTO cookies (identity, name, value, domain, path,"
+            " secure, http_only, expires, updated_at)"
+            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            ("1688:9.9.9.9", "prefixed", "v", ".1688.com", "/",
+             0, 0, None, "2025-08-08 00:00:00"))
+        conn.commit()
+        conn.close()
+
+        db = ShopDB(self.db_path)
+
+        def count(identity):
+            return db.conn.execute(
+                "SELECT COUNT(*) FROM cookies WHERE identity=?",
+                (identity,)).fetchone()[0]
+
+        # 原有裸键已迁移
+        self.assertEqual(count("1688:1.2.3.4"), 3)
+        # 已带前缀的不动
+        self.assertEqual(count("1688:9.9.9.9"), 1)
+        # 不应有两条 1688: 前缀叠加
+        self.assertEqual(count("1688:1688:9.9.9.9"), 0)
+
+        db.close()
+
+
+if __name__ == "__main__":
+    unittest.main()
