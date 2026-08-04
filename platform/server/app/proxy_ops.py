# -*- coding: utf-8 -*-
"""代理供应商 / 通道的写操作与探测逻辑。

与 app.db.connect 的只读约定不同，本模块自行打开写连接：
- 短事务（`with conn:` 立即提交），避免与采集进程争锁；
- busy_timeout = 30s，等待采集进程的写锁释放；
- 所有时间戳统一为北京时间字符串（UTC+8），与库内现有数据一致。

隧道清单来源（refresh_channels）：
1. provider config 里的 "tunnels" / "servers" 列表；
2. kind == "qingguo" 时回退到 .cache/qingguo_tunnel.json 的 servers
   （该文件由 fetcher 侧的 QingGuoProvider 维护，30 分钟轮换一次）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"

# 青果隧道入口缓存（与 fetcher/net/proxy/qingguo.py 的 CACHE_FILE 一致）
QINGGUO_CACHE_FILE = "/Volumes/DataDrive/proj/public/1699/.cache/qingguo_tunnel.json"

# 出口 IP 默认有效期（秒）：青果长效动态为 30 分钟轮换
DEFAULT_IP_TTL_SECONDS = 30 * 60

_BJT = timezone(timedelta(hours=8))


def now_bjt() -> str:
    return datetime.now(_BJT).strftime("%Y-%m-%d %H:%M:%S")


def _connect_write() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_provider(provider_id: int) -> dict | None:
    """读取 provider（config_json 已解析）及其全部通道，不存在返回 None。"""
    with _connect_write() as conn:
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            return None
        channels = conn.execute(
            "SELECT * FROM proxy_channels WHERE provider_id = ? ORDER BY id",
            (provider_id,)).fetchall()
    item = dict(row)
    try:
        item["config"] = json.loads(item.get("config_json") or "{}")
    except ValueError:
        item["config"] = {}
    item["channels"] = [dict(c) for c in channels]
    return item


def upsert_provider(kind: str, name: str, config: dict, enabled: bool = True) -> int:
    """按 (kind, name) 插入或更新 providers，返回 provider id。"""
    now = now_bjt()
    config_json = json.dumps(config or {}, ensure_ascii=False)
    with _connect_write() as conn:
        row = conn.execute(
            "SELECT id FROM providers WHERE kind = ? AND name = ? ORDER BY id",
            (kind, name)).fetchone()
        if row:
            pid = row["id"]
            with conn:  # 短事务
                conn.execute(
                    "UPDATE providers SET config_json = ?, enabled = ?, updated_at = ?"
                    " WHERE id = ?",
                    (config_json, int(bool(enabled)), now, pid))
        else:
            with conn:
                cur = conn.execute(
                    "INSERT INTO providers (kind, name, config_json, enabled,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (kind, name, config_json, int(bool(enabled)), now, now))
            pid = cur.lastrowid
    return pid


def update_provider(provider_id: int, *, name=None, config=None, enabled=None) -> bool:
    """按 id 局部更新 providers。返回是否有该行。"""
    existing = get_provider(provider_id)
    if not existing:
        return False
    new_name = existing["name"] if name is None else name
    new_config = existing["config"] if config is None else (config or {})
    new_enabled = existing["enabled"] if enabled is None else int(bool(enabled))
    with _connect_write() as conn:
        with conn:
            conn.execute(
                "UPDATE providers SET name = ?, config_json = ?, enabled = ?,"
                " updated_at = ? WHERE id = ?",
                (new_name, json.dumps(new_config, ensure_ascii=False),
                 new_enabled, now_bjt(), provider_id))
    return True


def set_enabled(provider_id: int, enabled: bool) -> bool:
    """开关 provider。返回是否有该行。"""
    with _connect_write() as conn:
        with conn:
            cur = conn.execute(
                "UPDATE providers SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(bool(enabled)), now_bjt(), provider_id))
    return cur.rowcount > 0


def _load_qingguo_cache_servers() -> list[str]:
    try:
        cache = json.loads(Path(QINGGUO_CACHE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    servers = cache.get("servers") or ([cache["server"]] if cache.get("server") else [])
    return [str(s).strip() for s in servers if str(s).strip()]


def _resolve_tunnels(kind: str, config: dict) -> list[str]:
    """确定该 provider 应有的隧道清单（去重、保序）。"""
    config = config or {}
    tunnels = config.get("tunnels") or config.get("servers")
    if not tunnels and kind == "qingguo":
        tunnels = _load_qingguo_cache_servers()
    seen, result = set(), []
    for t in tunnels or []:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def refresh_channels(provider: dict) -> dict:
    """按隧道清单同步 proxy_channels：新增缺失、多余标记 'disabled'、
    重新出现的复活为 'idle'，绝不删行。返回 {"added", "disabled", "revived", "tunnels"}。
    """
    pid = provider["id"]
    tunnels = _resolve_tunnels(provider.get("kind"), provider.get("config"))
    desired = set(tunnels)

    added, disabled, revived = [], [], []
    with _connect_write() as conn:
        existing = conn.execute(
            "SELECT id, tunnel, status FROM proxy_channels WHERE provider_id = ?",
            (pid,)).fetchall()
        by_tunnel = {r["tunnel"]: r for r in existing if r["tunnel"]}

        with conn:  # 单个短事务完成整次同步
            for t in tunnels:
                row = by_tunnel.get(t)
                if row is None:
                    conn.execute(
                        "INSERT INTO proxy_channels (provider_id, tunnel, status)"
                        " VALUES (?, ?, 'idle')",
                        (pid, t))
                    added.append(t)
                elif row["status"] == "disabled":
                    conn.execute(
                        "UPDATE proxy_channels SET status = 'idle' WHERE id = ?",
                        (row["id"],))
                    revived.append(t)
            for t, row in by_tunnel.items():
                if t not in desired and row["status"] != "disabled":
                    conn.execute(
                        "UPDATE proxy_channels SET status = 'disabled' WHERE id = ?",
                        (row["id"],))
                    disabled.append(t)

    return {"tunnels": tunnels, "added": added, "disabled": disabled,
            "revived": revived}


def _extract_exit_ip(resp_text: str) -> str:
    """从 ipinfo.io/json 或 httpbin.org/ip 的响应里取出口 IP。"""
    try:
        data = json.loads(resp_text)
    except ValueError:
        return resp_text.strip()[:64]
    ip = data.get("ip") or data.get("origin") or ""
    # httpbin 的 origin 可能是 "1.2.3.4, 5.6.7.8"
    return ip.split(",")[0].strip()


def probe_channel(channel: dict, config: dict | None = None) -> dict:
    """经隧道代理探测出口 IP 并落库。

    channel: 至少含 id / tunnel 的 dict；config 缺省时调用方需自行传入
    provider 的 config（含 auth_key/auth_pwd，可选 test_url、ip_ttl_seconds）。
    """
    import requests  # 延迟导入，与 fetcher 侧风格一致

    config = config or channel.get("config") or {}
    channel_id = channel.get("id")
    tunnel = (channel.get("tunnel") or "").strip()
    if not tunnel:
        return {"tunnel": tunnel, "ok": False, "error": "empty tunnel"}

    user = config.get("auth_key") or config.get("username") or ""
    pwd = config.get("auth_pwd") or config.get("password") or ""
    auth = f"{user}:{pwd}@" if (user or pwd) else ""
    proxy_url = f"http://{auth}{tunnel}"
    proxies = {"http": proxy_url, "https": proxy_url}
    test_url = config.get("test_url") or "https://ipinfo.io/json"
    ttl = int(config.get("ip_ttl_seconds") or DEFAULT_IP_TTL_SECONDS)

    now = now_bjt()
    try:
        resp = requests.get(test_url, proxies=proxies, timeout=10)
        resp.raise_for_status()
        exit_ip = _extract_exit_ip(resp.text)
        if not exit_ip:
            raise ValueError(f"无法从响应解析出口 IP: {resp.text[:120]}")
        expires = (datetime.now(_BJT) + timedelta(seconds=ttl)
                   ).strftime("%Y-%m-%d %H:%M:%S")
        if channel_id is not None:
            with _connect_write() as conn:
                with conn:
                    conn.execute(
                        "UPDATE proxy_channels SET exit_ip = ?, status = 'ready',"
                        " ip_expires_at = ?, last_probe_at = ? WHERE id = ?",
                        (exit_ip, expires, now, channel_id))
        return {"tunnel": tunnel, "ok": True, "exit_ip": exit_ip}
    except Exception as e:  # 网络失败也要落库 status='error'
        error = f"{type(e).__name__}: {e}"[:200]
        if channel_id is not None:
            with _connect_write() as conn:
                with conn:
                    conn.execute(
                        "UPDATE proxy_channels SET status = 'error',"
                        " last_probe_at = ? WHERE id = ?",
                        (now, channel_id))
        return {"tunnel": tunnel, "ok": False, "error": error}
