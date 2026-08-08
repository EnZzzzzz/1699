# -*- coding: utf-8 -*-
"""daemon 消费者状态心跳 + 代理通道租约（P4 可观测底座）。

写方 = fetcher daemon（唯一写者）：
- consumer_status：claim/finish/release/冷却登记时即时 upsert，10s 心跳线程
  批量刷新 updated_at，退出 clear；
- proxy_channels.used_by_task：启动按 tunnel 匹配租约（语义复用为 consumer
  租约，列名不改），退出清零（release_channels）。

读方 = 平台 dispatcher API（看板，见 P4-2/2.3）。本模块只写，不读。

线程模型：sqlite3 连接不可跨线程。ConsumerStatusStore 按线程懒建独立
ShopDB（worker 线程 / 心跳线程 / 主线程各自持有），close() 只关当前线程
连接（daemon 收尾用）；worker 线程的连接随线程结束由 GC 回收（SQLite
连接对象析构即释放，daemon 常驻期间由心跳线程周期性复用自身连接）。

DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，爬虫可能正在写库）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fetcher.db import ShopDB


# upsert 字段哨兵：未传 = 保留原值；显式传 None = 清空该字段
_KEEP = object()


def _bj_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ConsumerStatusStore:
    """consumer_status / proxy_channels 租约的 daemon 侧写入口（线程安全）。

    用法：
        store = ConsumerStatusStore(db_path)   # db 路径（str | Path）
        store.upsert("w0", "browser", tunnel=..., queue=..., item_id=...,
                     batch_id=..., cooldowns=...)
        store.heartbeat_all(["w0", "w1"])   # 10s 心跳线程
        store.clear("w0")                   # 退出
        store.lease_channels("w0", [tunnel...])   # 启动认领
        store.release_channels("w0")        # 退出释放
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._local = threading.local()

    def _db(self) -> ShopDB:
        """当前线程的独立 ShopDB（懒建；sqlite 连接不可跨线程）。"""
        db = getattr(self._local, "db", None)
        if db is None:
            db = self._local.db = ShopDB(self.db_path)
        return db

    # ---- consumer_status ----

    def upsert(self, consumer_id: str, kind: str, *,
               tunnel=_KEEP, exit_ip=_KEEP,
               queue=_KEEP, item_id=_KEEP,
               batch_id=_KEEP,
               cooldowns=_KEEP) -> None:
        """UPSERT 一行消费者状态。

        字段哨兵语义：未传 = 保留原值（部分更新/心跳不 clobber）；
        显式传 None = 清空该字段（item 完成/切换时归零）。
        cooldowns dict[site, epoch] → cooldowns_json。
        """
        db = self._db()
        conn = db.conn
        now = _bj_now()
        # 现有行（若无则全 None 打底）
        row = conn.execute(
            "SELECT * FROM consumer_status WHERE consumer_id=?",
            (consumer_id,)).fetchone()
        base = dict(row) if row else {
            "tunnel": None, "exit_ip": None, "current_queue": None,
            "current_item_id": None, "current_batch_id": None,
            "cooldowns_json": None}
        fields = {
            "tunnel": tunnel if tunnel is not _KEEP else base.get("tunnel"),
            "exit_ip": exit_ip if exit_ip is not _KEEP else base.get("exit_ip"),
            "current_queue": (queue if queue is not _KEEP
                              else base.get("current_queue")),
            "current_item_id": (item_id if item_id is not _KEEP
                                else base.get("current_item_id")),
            "current_batch_id": (batch_id if batch_id is not _KEEP
                                 else base.get("current_batch_id")),
            "cooldowns_json": (
                json.dumps(cooldowns or {}, ensure_ascii=False)
                if cooldowns is not _KEEP and cooldowns is not None
                else (None if cooldowns is None
                      else base.get("cooldowns_json"))),
        }
        conn.execute(
            """INSERT INTO consumer_status
                   (consumer_id, kind, tunnel, exit_ip, current_queue,
                    current_item_id, current_batch_id, cooldowns_json,
                    updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(consumer_id) DO UPDATE SET
                   kind = excluded.kind,
                   tunnel = excluded.tunnel,
                   exit_ip = excluded.exit_ip,
                   current_queue = excluded.current_queue,
                   current_item_id = excluded.current_item_id,
                   current_batch_id = excluded.current_batch_id,
                   cooldowns_json = excluded.cooldowns_json,
                   updated_at = excluded.updated_at""",
            (consumer_id, kind, fields["tunnel"], fields["exit_ip"],
             fields["current_queue"], fields["current_item_id"],
             fields["current_batch_id"], fields["cooldowns_json"],
             now))
        conn.commit()

    def clear(self, consumer_id: str) -> None:
        """删除该消费者状态行（daemon 退出时调用）。"""
        conn = self._db().conn
        conn.execute(
            "DELETE FROM consumer_status WHERE consumer_id=?", (consumer_id,))
        conn.commit()

    def heartbeat_all(self, consumers: list[str]) -> None:
        """批量刷新在册消费者的心跳时间（10s 心跳线程）。

        只更新 updated_at，保留其余字段（不 clobber current_*）。
        不在册的 consumer_id 不重建（已 clear 的行保持消失）。
        """
        conn = self._db().conn
        now = _bj_now()
        for cid in consumers:
            conn.execute(
                "UPDATE consumer_status SET updated_at=? WHERE consumer_id=?",
                (now, cid))
        conn.commit()

    # ---- proxy_channels 租约（列名 used_by_task 语义复用为 consumer 租约）----

    def lease_channels(self, consumer_id: str,
                       tunnels: list[str]) -> int:
        """按 tunnel 匹配认领通道：used_by_task=consumer_id。返回行数。"""
        if not tunnels:
            return 0
        conn = self._db().conn
        placeholders = ",".join("?" * len(tunnels))
        cur = conn.execute(
            f"UPDATE proxy_channels SET used_by_task=? "
            f"WHERE tunnel IN ({placeholders})",
            (consumer_id, *tunnels))
        conn.commit()
        return cur.rowcount

    def release_channels(self, consumer_id: str) -> int:
        """释放该消费者名下的全部通道租约（退出清零）。返回行数。"""
        conn = self._db().conn
        cur = conn.execute(
            "UPDATE proxy_channels SET used_by_task=NULL"
            " WHERE used_by_task=?", (consumer_id,))
        conn.commit()
        return cur.rowcount

    def close(self) -> None:
        """关闭当前线程的连接（daemon 收尾调用，防主线程连接泄漏）。

        worker/心跳线程的连接随线程结束由 GC 回收；主线程连接显式关闭。
        """
        db = getattr(self._local, "db", None)
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass
            self._local.db = None
