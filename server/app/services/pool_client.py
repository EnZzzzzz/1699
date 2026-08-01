# -*- coding: utf-8 -*-
"""
共享池客户端（Celery worker 侧）。

worker 不直连厂商 API：通道申请/归还/使用事件上报统一走本机 FastAPI
（POST /api/pool/acquire|release|events）；构造代理所需的厂商账密从本机
SQLite providers.config_json 直读（worker 与 API 同机同库，不走网络）。

心跳：写 Redis 键 heartbeat:task:{id}（供主进程 PoolManager.reclaim_stale
兜底回收崩溃 worker 的通道）；Redis 不可用时降级为无操作。
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlparse

import requests
from loguru import logger

from .. import config
from ..db import SessionLocal
from ..models import Provider
from .proxy.base import Channel, get_provider

HEARTBEAT_PREFIX = "heartbeat:task:"
CONFIRM_PREFIX = "task:confirmed:"


def _api_base() -> str:
    return f"http://{config.HOST}:{config.PORT}"


class PoolAcquireTimeout(RuntimeError):
    """等待共享池分配通道超时。"""


class PoolClient:
    def __init__(self, task_id: int, api_base: str | None = None):
        self.task_id = task_id
        self.base = (api_base or _api_base()).rstrip("/")
        self.channels: list[dict] = []
        self._event_buf: list[dict] = []
        self._buf_lock = threading.Lock()

    # ---------------- acquire / release ----------------
    def acquire(self, n: int, use_proxy: bool = True,
                wait: bool = True, poll_interval: float = 5.0,
                timeout: float = 600.0,
                should_stop=None) -> list[dict]:
        """申请 n 条通道。不足时轮询等待（任务状态由 API 置 waiting_channel）。

        should_stop: 可选回调，返回 True 时中止等待（协作式停止）。
        """
        deadline = time.time() + timeout
        while True:
            r = requests.post(f"{self.base}/api/pool/acquire",
                              json={"task_id": self.task_id, "n": n,
                                    "use_proxy": use_proxy}, timeout=15)
            r.raise_for_status()
            body = r.json()
            if body.get("granted"):
                self.channels = body["channels"]
                logger.info("task {} 申请到 {} 条{}通道：{}",
                            self.task_id, len(self.channels),
                            "代理" if use_proxy else "直连",
                            "、".join(f"#{c['id']}" for c in self.channels))
                return self.channels
            if not wait:
                return []
            if should_stop and should_stop():
                logger.warning("task {} 等待通道期间收到停止请求", self.task_id)
                raise PoolAcquireTimeout("等待通道期间收到停止请求")
            if time.time() > deadline:
                logger.warning("task {} 等待 {}s 仍未分配到通道",
                               self.task_id, timeout)
                raise PoolAcquireTimeout(f"等待 {timeout}s 仍未分配到通道")
            time.sleep(poll_interval)

    def release(self) -> int:
        if not self.channels:
            return 0
        try:
            r = requests.post(f"{self.base}/api/pool/release",
                              json={"task_id": self.task_id}, timeout=15)
            r.raise_for_status()
            released = r.json().get("released", 0)
            logger.info("task {} 已释放 {} 条通道", self.task_id, released)
            return released
        finally:
            self.channels = []

    # ---------------- 换通道（release 旧 + 随机重抽，池侧原子）----------------
    def swap_channel(self, channel: dict) -> tuple[dict, bool]:
        """释放 channel 回池并随机重抽一条（不含刚释放的；池里只有它则拿回）。

        返回 (新通道 dict, reused)；reused=True 表示池内无其他空闲通道、
        拿回的是原通道。调用方负责同步更新 self.channels 与事件埋点。
        """
        r = requests.post(f"{self.base}/api/pool/swap",
                          json={"task_id": self.task_id,
                                "channel_id": channel["id"]}, timeout=15)
        r.raise_for_status()
        body = r.json()
        new_ch = body["channel"]
        for i, c in enumerate(self.channels):
            if c["id"] == channel["id"]:
                self.channels[i] = new_ch
                break
        else:
            self.channels.append(new_ch)
        logger.info("task {} 换通道：#{} -> #{}{}",
                    self.task_id, channel["id"], new_ch["id"],
                    "（池内无其他空闲，拿回旧通道）" if body.get("reused") else "")
        return new_ch, bool(body.get("reused"))

    # ---------------- 代理构造（账密从本机库直读）----------------
    def channel_proxy(self, channel: dict) -> tuple[str | None, tuple | None]:
        """返回 (proxy_server, (user, pwd))；直连通道返回 (None, None)。"""
        if channel.get("is_direct") or not channel.get("tunnel"):
            return None, None
        with SessionLocal() as db:
            p = db.get(Provider, channel["provider_id"])
            if p is None:
                raise RuntimeError(f"通道 {channel['id']} 的 provider 不存在")
            cfg = p.config
            kind = p.kind
        provider = get_provider(kind)
        proxies = provider.make_proxies(Channel(tunnel=channel["tunnel"]), cfg)
        u = urlparse(proxies["https"])
        return f"{u.hostname}:{u.port}", (u.username, u.password)

    def req_proxies(self, channel: dict) -> dict | None:
        """requests 用的代理字典（直连为 None）。"""
        server, auth = self.channel_proxy(channel)
        if not server:
            return None
        url = f"http://{auth[0]}:{auth[1]}@{server}"
        return {"http": url, "https": url}

    # ---------------- 使用事件上报（缓冲批量）----------------
    def report(self, channel: dict, result: str = "ok",
               task_type: str | None = None, exit_ip: str | None = None):
        ev = {"channel_id": channel["id"], "task_id": self.task_id,
              "task_type": task_type, "exit_ip": exit_ip, "result": result}
        with self._buf_lock:
            self._event_buf.append(ev)
            if len(self._event_buf) >= 20:
                self.flush_events()

    def flush_events(self):
        with self._buf_lock:
            batch, self._event_buf = self._event_buf, []
        if not batch:
            return
        try:
            requests.post(f"{self.base}/api/pool/events", json=batch,
                          timeout=15).raise_for_status()
        except Exception as e:  # noqa: BLE001 - 上报失败不阻塞采集
            logger.warning("task {} 使用事件上报失败（{} 条丢弃）: {}",
                           self.task_id, len(batch), e)


# ---------------- Redis 心跳 / 确认 ----------------

_redis_client = None
_redis_failed = False


def _redis():
    """懒加载 Redis 客户端；不可用时返回 None（降级无操作）。"""
    global _redis_client, _redis_failed
    if _redis_failed:
        return None
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis.from_url(config.REDIS_URL,
                                                 socket_timeout=3)
            _redis_client.ping()
        except Exception:
            _redis_failed = True
            _redis_client = None
    return _redis_client


def heartbeat(task_id: int) -> None:
    """写任务心跳（epoch 秒），TTL 300s；主进程据此回收崩溃 worker 的通道。"""
    r = _redis()
    if r is None:
        return
    try:
        r.set(HEARTBEAT_PREFIX + str(task_id), str(time.time()), ex=300)
    except Exception:
        pass


def clear_heartbeat(task_id: int) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.delete(HEARTBEAT_PREFIX + str(task_id))
    except Exception:
        pass


def read_heartbeats() -> dict[int, float]:
    """主进程侧：读取全部任务心跳 {task_id: epoch}。"""
    r = _redis()
    if r is None:
        return {}
    try:
        out = {}
        for key in r.scan_iter(HEARTBEAT_PREFIX + "*"):
            try:
                out[int(key.decode().rsplit(":", 1)[-1])] = float(r.get(key))
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return {}


def wait_confirmation(task_id: int, timeout: float = 600.0,
                      poll: float = 3.0, should_stop=None) -> bool:
    """headed 模式人工确认：等待 POST /api/tasks/{id}/confirm 写入的 Redis 标记。

    返回 True=已确认；False=超时/停止（调用方按取消处理）。
    """
    r = _redis()
    if r is None:
        return True  # 无 Redis 时跳过人工确认（等价 -y）
    deadline = time.time() + timeout
    while time.time() < deadline:
        if should_stop and should_stop():
            return False
        try:
            if r.get(CONFIRM_PREFIX + str(task_id)):
                r.delete(CONFIRM_PREFIX + str(task_id))
                return True
        except Exception:
            return True
        time.sleep(poll)
    return False


def set_confirmation(task_id: int) -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        r.set(CONFIRM_PREFIX + str(task_id), "1", ex=3600)
        return True
    except Exception:
        return False


def swap_channel_with_events(rt, pool_client: PoolClient, channel: dict,
                             worker_id: int, note: str = "") -> dict:
    """换通道（release 当前回池 + 全池随机重抽，池侧原子）并埋事件。

    两个 worker 共用（rt 鸭子类型：只要有 emit）。
    池内无其他空闲通道时拿回旧通道并记 warning 注明。
    返回（可能不变的）新通道；API 失败抛异常由调用方处置。
    """
    old_ip = channel.get("exit_ip") or channel.get("tunnel") or "?"
    new_ch, reused = pool_client.swap_channel(channel)
    new_ip = new_ch.get("exit_ip") or new_ch.get("tunnel") or "?"
    suffix = f"（{note}）" if note else ""
    if reused:
        rt.emit("warning", f"池内无其他空闲通道，继续使用原通道"
                f" #{new_ch['id']}（{new_ip}）{suffix}",
                {"worker": worker_id, "channel_id": new_ch["id"],
                 "exit_ip": new_ip, "reused": True})
    else:
        rt.emit("info", f"已换通道：#{channel['id']}（{old_ip}）→ "
                f"#{new_ch['id']}（{new_ip}）{suffix}",
                {"worker": worker_id, "old_channel": channel["id"],
                 "new_channel": new_ch["id"], "old_ip": old_ip,
                 "new_ip": new_ip, "reused": False})
    return new_ch
