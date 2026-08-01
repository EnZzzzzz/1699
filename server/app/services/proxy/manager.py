# -*- coding: utf-8 -*-
"""
全局共享池调度器 ProxyPoolManager（docs/service-architecture.md §6）。

运行在 FastAPI 主进程，线程安全，状态落 proxy_channels 表：

- acquire(task_id, n)：空闲通道充足则标记 in_use 并返回；不足返回 []，
  任务进 waiting 队列（FIFO，有通道释放时按入队顺序唤醒）。
- release(task_id)：任务结束/停止/异常时释放全部占用，随后尝试唤醒等待队列。
- 直连（provider_id NULL）是永远可用的特殊通道（不互斥，但使用事件照常记录）。
- 心跳超时回收：reclaim_stale(last_heartbeat, timeout_seconds) 由 M4 任务心跳驱动，
  防止 worker 崩溃导致通道泄漏；force_release(task_id) 为手工兜底。
- 出口 IP 探测：probe_all() 由主进程定时器调用（默认 60s/通道，可配置开关），
  更新 exit_ip / ip_expires_at（青果按"探测到 IP 变化 +30min"推算轮换时间）。
"""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from typing import Callable

import requests

from ... import config as app_config
from ...models import ProxyChannel, Provider
from .base import Channel, get_provider


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _plus_seconds(seconds: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + seconds))


class PoolManager:
    def __init__(self, session_factory: Callable):
        self._Session = session_factory
        self._lock = threading.RLock()
        # 等待队列：元素 {"task_id", "n", "use_proxy", "enqueued_at"}
        self._waiting: deque[dict] = deque()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def ensure_direct_channel(self) -> int:
        """确保存在直连特殊通道（provider_id NULL, tunnel NULL）。返回 channel id。

        注意：UNIQUE(provider_id, tunnel) 对 NULL 不生效，故这里在锁内查重插入。
        """
        with self._lock, self._Session() as db:
            row = db.query(ProxyChannel).filter(ProxyChannel.provider_id.is_(None)).first()
            if row:
                return row.id
            ch = ProxyChannel(provider_id=None, tunnel=None, status="idle")
            db.add(ch)
            db.commit()
            return ch.id

    # ------------------------------------------------------------------
    # acquire / release
    # ------------------------------------------------------------------
    def acquire(self, task_id: int, n: int = 1, use_proxy: bool = True) -> list[dict]:
        """为任务申请 n 条通道。

        - use_proxy=False（直连模式）：返回直连特殊通道（不互斥，不占额度）。
        - 空闲通道充足：标记 in_use 并返回通道列表。
        - 不足：返回 []，任务进等待队列（去重；任务侧应置 waiting_channel 状态）。
        """
        with self._lock:
            if not use_proxy:
                return [self._direct_channel_dict()]

            with self._Session() as db:
                idle = (db.query(ProxyChannel)
                        .filter(ProxyChannel.provider_id.isnot(None),
                                ProxyChannel.status == "idle")
                        .order_by(ProxyChannel.id).all())
                if len(idle) < n:
                    self._enqueue(task_id, n, use_proxy)
                    return []
                # 空闲通道随机抽取（避免多任务总是抢同一批前置通道）
                picked = random.sample(idle, n)
                now = _now()
                for ch in picked:
                    ch.status = "in_use"
                    ch.used_by_task = task_id
                    ch.last_probe_at = ch.last_probe_at or now
                db.commit()
                return [ch.to_dict() for ch in picked]

    def release(self, task_id: int) -> int:
        """释放任务占用的全部通道，返回释放条数；随后按 FIFO 唤醒等待队列。"""
        with self._lock, self._Session() as db:
            rows = (db.query(ProxyChannel)
                    .filter(ProxyChannel.used_by_task == task_id).all())
            for ch in rows:
                ch.status = "idle"
                ch.used_by_task = None
            db.commit()
            released = len(rows)
        self._drain_waiting()
        return released

    def force_release(self, task_id: int) -> int:
        """手工兜底释放（等价 release，语义上供管理端/排障调用）。"""
        return self.release(task_id)

    def swap_channel(self, task_id: int, channel_id: int) -> dict | None:
        """原子换通道：释放 task 占用的 channel_id，随机改占一条其他空闲通道。

        全程一把锁，无"释放后被别的任务抢走"的空窗：
        - 池里有其他空闲通道：随机选一条换上，旧通道回池（reused=False）；
        - 池里暂时只有旧通道可用：不换，继续持有旧通道（reused=True，
          调用方记事件注明"池内无其他空闲通道"）；
        - 旧通道不存在/不属于该任务：返回 None（调用方按异常处置）。

        换进换出在锁内同时完成，池空闲数不变，故不触发等待队列唤醒。
        直连通道不互斥，不在此语义内（调用方只在代理模式调用）。
        """
        with self._lock, self._Session() as db:
            old = db.get(ProxyChannel, channel_id)
            if old is None or old.used_by_task != task_id:
                return None
            idle = (db.query(ProxyChannel)
                    .filter(ProxyChannel.provider_id.isnot(None),
                            ProxyChannel.status == "idle",
                            ProxyChannel.id != channel_id).all())
            if not idle:
                d = old.to_dict()
                d["reused"] = True
                return d
            new = random.choice(idle)
            old.status = "idle"
            old.used_by_task = None
            new.status = "in_use"
            new.used_by_task = task_id
            new.last_probe_at = new.last_probe_at or _now()
            db.commit()
            d = new.to_dict()
            d["reused"] = False
            return d

    def reclaim_stale(self, last_heartbeat: dict[int, float],
                      timeout_seconds: int = 90) -> list[int]:
        """心跳超时回收（防 worker 崩溃通道泄漏）。

        last_heartbeat: {task_id: 最近心跳的 epoch 秒}（M4 任务侧经 Redis/REST 上报）。
        对"占用着通道但超过 timeout_seconds 无心跳"的任务强制释放。
        返回被回收的 task_id 列表。
        """
        now = time.time()
        with self._lock, self._Session() as db:
            busy_task_ids = {r[0] for r in db.query(ProxyChannel.used_by_task)
                             .filter(ProxyChannel.used_by_task.isnot(None)).all()}
        stale = [tid for tid in busy_task_ids
                 if now - last_heartbeat.get(tid, 0) > timeout_seconds]
        for tid in stale:
            self.release(tid)
        return stale

    # ------------------------------------------------------------------
    # 等待队列
    # ------------------------------------------------------------------
    def _enqueue(self, task_id: int, n: int, use_proxy: bool) -> None:
        if any(w["task_id"] == task_id for w in self._waiting):
            return
        self._waiting.append({
            "task_id": task_id, "n": n, "use_proxy": use_proxy,
            "enqueued_at": _now(),
        })

    def dequeue(self, task_id: int) -> bool:
        """任务取消/启动失败时从等待队列移除。返回是否移除。"""
        with self._lock:
            for w in list(self._waiting):
                if w["task_id"] == task_id:
                    self._waiting.remove(w)
                    return True
        return False

    def waiting(self) -> list[dict]:
        with self._lock:
            return list(self._waiting)

    def _drain_waiting(self) -> None:
        """有通道释放后，按入队顺序尝试满足等待队列（满足不了就停，保证 FIFO）。"""
        with self._lock:
            while self._waiting:
                w = self._waiting[0]
                got = self.acquire(w["task_id"], w["n"], w["use_proxy"])
                if not got:
                    break
                self._waiting.popleft()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _direct_channel_dict(self) -> dict:
        with self._Session() as db:
            ch = db.query(ProxyChannel).filter(ProxyChannel.provider_id.is_(None)).first()
            if ch is None:
                cid = self.ensure_direct_channel()
                ch = db.get(ProxyChannel, cid)
            return ch.to_dict()

    def list_channels(self) -> list[dict]:
        """全部通道（直连置顶），附 provider 信息。"""
        with self._Session() as db:
            providers = {p.id: p for p in db.query(Provider).all()}
            rows = db.query(ProxyChannel).order_by(ProxyChannel.id).all()
            out = []
            for ch in rows:
                d = ch.to_dict()
                if ch.provider_id and ch.provider_id in providers:
                    p = providers[ch.provider_id]
                    d["provider_kind"] = p.kind
                    d["provider_name"] = p.name
                else:
                    d["provider_kind"] = "direct"
                    d["provider_name"] = "本机 IP"
                out.append(d)
            out.sort(key=lambda d: (not d["is_direct"], d["id"]))
            return out

    def occupancy(self) -> dict:
        with self._Session() as db:
            rows = db.query(ProxyChannel.status,
                            ProxyChannel.provider_id).all()
        proxy = [r for r in rows if r[1] is not None]
        return {
            "total": len(proxy),
            "in_use": sum(1 for r in proxy if r[0] == "in_use"),
            "idle": sum(1 for r in proxy if r[0] == "idle"),
            "error": sum(1 for r in proxy if r[0] == "error"),
            "waiting_tasks": len(self.waiting()),
        }

    # ------------------------------------------------------------------
    # 出口 IP 探测（由主进程定时器调用；阻塞 IO，调用方用线程池）
    # ------------------------------------------------------------------
    def probe_all(self) -> list[dict]:
        """逐通道经代理请求探测 URL，更新 exit_ip / ip_expires_at / last_probe_at。

        直连通道探测本机出口 IP。返回每通道探测结果摘要。
        """
        with self._Session() as db:
            providers = {p.id: p for p in db.query(Provider).filter(Provider.enabled == 1).all()}
            channels = db.query(ProxyChannel).order_by(ProxyChannel.id).all()
            snapshot = [(ch.id, ch.provider_id, ch.tunnel, ch.exit_ip, ch.status)
                        for ch in channels]
            configs = {pid: (p.kind, p.config) for pid, p in providers.items()}

        results = []
        updates: list[tuple[int, str | None, str | None, str, bool]] = []
        for cid, pid, tunnel, old_ip, status in snapshot:
            if pid is not None and pid not in configs:
                continue  # provider 已禁用/删除，跳过
            ok, new_ip, err = False, None, None
            try:
                if pid is None:
                    r = requests.get(app_config.EXIT_IP_PROBE_URL,
                                     headers={"Connection": "close"},
                                     timeout=app_config.EXIT_IP_PROBE_TIMEOUT)
                    new_ip, ok = r.json().get("ip"), True
                else:
                    kind, cfg = configs[pid]
                    provider = get_provider(kind)
                    proxies = provider.make_proxies(Channel(tunnel=tunnel), cfg)
                    r = requests.get(app_config.EXIT_IP_PROBE_URL, proxies=proxies,
                                     headers={"Connection": "close"},
                                     timeout=app_config.EXIT_IP_PROBE_TIMEOUT)
                    new_ip, ok = r.json().get("ip"), True
            except Exception as e:  # noqa: BLE001 - 单通道失败不影响其他通道
                err = str(e)
            ip_changed = ok and new_ip and new_ip != old_ip
            ttl = (get_provider(configs[pid][0]).exit_ip_ttl(configs[pid][1])
                   if pid is not None else 0)
            expires = _plus_seconds(ttl) if ip_changed and ttl else None
            updates.append((cid, new_ip if ok else old_ip, expires, _now(), ok))
            results.append({"channel_id": cid, "ok": ok, "exit_ip": new_ip,
                            "ip_changed": bool(ip_changed), "error": err})

        with self._Session() as db:
            for cid, ip, expires, probe_at, ok in updates:
                ch = db.get(ProxyChannel, cid)
                if ch is None:
                    continue
                ch.exit_ip = ip
                ch.last_probe_at = probe_at
                if expires:
                    ch.ip_expires_at = expires
                # 探测失败的空闲通道标记 error；in_use 不动状态（任务侧自行处置）
                if not ok and ch.status == "idle":
                    ch.status = "error"
                elif ok and ch.status == "error":
                    ch.status = "idle"
            db.commit()
        return results
