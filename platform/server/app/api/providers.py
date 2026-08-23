# -*- coding: utf-8 -*-
"""代理供应商管理 API。

路由前缀 /providers（由 app.api 挂载在 /api 下）：
- GET    /providers                     现有行为：列表，含解析后的 config_json 与 proxy_channels
- POST   /providers                     创建/按 (kind,name) 更新，并自动 refresh_channels
- PUT    /providers/{id}                局部更新；config 变化时自动 refresh_channels
- POST   /providers/{id}/probe          并发探测全部通道出口 IP（ThreadPoolExecutor ≤ 8）
- POST   /providers/{id}/channels/refresh  手动重同步通道清单
- GET    /providers/config-schema       青果隧道缓存与 provider config 的键结构（值打码）
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import proxy_ops
from app.db import connect

router = APIRouter(prefix="/providers")

MAX_PROBE_WORKERS = 8
PROBE_SKIP_STATUSES = {"disabled"}


def _parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


# ==================== 请求体 ====================

class ProviderUpsert(BaseModel):
    kind: str = "qingguo"
    name: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    enabled: Optional[bool] = None


# ==================== 读取 ====================

def _bd_offset(config) -> float:
    """brightdata provider config 里的 billing_offset（试用额度等抵扣差值）。

    官方 /balance API 的 balance 只扣待结算费用，不含试用额度（trial credit）
    覆盖的用量，与后台 Billing 页 Balance 差一个固定抵扣额；该差值手工校准后
    存 config.billing_offset（表单保存后为字符串，需容忍解析）。新账期或新增
    赠送额度后需重新校准。非法值按 0 处理。
    """
    try:
        return float((config or {}).get("billing_offset") or 0)
    except (TypeError, ValueError):
        return 0.0


def _provider_billing(conn) -> dict:
    """从 cost_records real 行取各供应商费用侧信息，键为 (kind, name)。

    - brightdata：最新一条 BALANCE 快照（detail_json 含 pending_costs），
      按 config.billing_offset 校准为与官方后台一致的两个口径：
      可用余额 = balance − offset（对应后台 Balance），
      本账期消耗 = pending_costs + offset（对应后台 Consumed）
    - apify：订阅+后付费无余额概念，取最新 USAGE_CYCLE 快照（当前账期累计
      用量 + detail 里的月度上限）；无快照时退化为本月真实账单累计
      （date 为 Apify 原始 UTC 账单日期，月界按北京月份近似）
    cost_records 表不存在（migrate 未跑）时返回空。
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "cost_records" not in tables:
        return {}
    result = {}
    # as_of 用 synced_at（北京时间，精确到秒），反映快照/数据的实际同步时刻
    row = conn.execute(
        "SELECT usd, synced_at, detail_json FROM cost_records"
        " WHERE provider='brightdata' AND service='BALANCE' AND source='real'"
        " ORDER BY date DESC, synced_at DESC LIMIT 1").fetchone()
    if row:
        pending = (_parse_json(row["detail_json"]) or {}).get("pending_costs")
        for name, cfg in conn.execute(
                "SELECT name, config_json FROM providers"
                " WHERE kind='brightdata'").fetchall():
            offset = _bd_offset(_parse_json(cfg))
            info = {
                "label": "可用余额",
                "usd": round(row["usd"] - offset, 2),
                "as_of": row["synced_at"],
            }
            if pending is not None:
                info["consumed"] = round(float(pending) + offset, 2)
            result[("brightdata", name)] = info
    month0 = time.strftime("%Y-%m-01")
    for name, in conn.execute(
            "SELECT name FROM providers WHERE kind='apify'").fetchall():
        snap = conn.execute(
            "SELECT usd, synced_at, detail_json FROM cost_records"
            " WHERE provider='apify' AND channel=? AND service='USAGE_CYCLE'"
            " AND source='real' ORDER BY date DESC, synced_at DESC LIMIT 1",
            (f"account:{name}",)).fetchone()
        if snap:
            detail = _parse_json(snap["detail_json"]) or {}
            result[("apify", name)] = {
                "label": "本账期已用", "usd": snap["usd"],
                "as_of": snap["synced_at"],
                "limit": detail.get("maxMonthlyUsageUsd")}
            continue
        agg = conn.execute(
            "SELECT SUM(usd), MAX(synced_at) FROM cost_records"
            " WHERE provider='apify' AND channel=? AND source='real'"
            " AND date >= ? AND service != 'USAGE_CYCLE'",
            (f"account:{name}", month0)).fetchone()
        if agg and agg["SUM(usd)"] is not None:
            result[("apify", name)] = {
                "label": "本月已用", "usd": agg["SUM(usd)"],
                "as_of": agg["MAX(synced_at)"]}
    return result


@router.get("")
def list_providers():
    with connect() as conn:
        providers = conn.execute(
            "SELECT * FROM providers ORDER BY id").fetchall()
        channels = conn.execute(
            "SELECT * FROM proxy_channels ORDER BY provider_id, id").fetchall()
        billing = _provider_billing(conn)

    by_provider = {}
    for ch in channels:
        by_provider.setdefault(ch["provider_id"], []).append(dict(ch))

    result = []
    for p in providers:
        item = dict(p)
        item["config_json"] = _parse_json(item.get("config_json"))
        item["proxy_channels"] = by_provider.get(p["id"], [])
        item["billing"] = billing.get((p["kind"], p["name"]))
        result.append(item)
    return result


def _mask(value):
    """打码：长字符串保留前 4 位 + ***，其余类型原样返回（结构保留）。"""
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    if isinstance(value, str) and len(value) > 4:
        return value[:4] + "***"
    return value


# 各 kind provider config 的默认键结构模板
# 青果（与 fetcher/net/proxy/qingguo.py CONFIG 对齐）
_QINGGUO_CONFIG_TEMPLATE = {
    "key": "",          # API 公共参数 key（Authkey）
    "auth_key": "",     # 代理用户名 = Authkey
    "auth_pwd": "",     # 代理密码 = Authpwd
    "channels": 5,      # 通道数
    "api_base": "https://longterm.proxy.qg.net",
    "area": "",         # 按地区提取，留空不筛选
    "isp": 0,           # 0 不筛选 / 1 电信 / 2 移动 / 3 联通
    "test_url": "https://ipinfo.io/json",
    "ip_ttl_seconds": 1800,  # 出口 IP 有效期（可选，默认 30 分钟）
}

# Apify（WhatsApp 查号 API 等 actor 服务，REST 调用只需 token）
_APIFY_CONFIG_TEMPLATE = {
    "api_token": "",    # Apify Console → Settings → API tokens
}

_CONFIG_TEMPLATES = {
    "qingguo": _QINGGUO_CONFIG_TEMPLATE,
    "apify": _APIFY_CONFIG_TEMPLATE,
}


@router.get("/config-schema")
def config_schema(kind: str = "qingguo"):
    """返回指定 kind 的 provider config 键结构（值打码），供前端表单参考。

    缺省 kind=qingguo 保持历史行为（附青果隧道缓存结构）；
    未知 kind 返回 422。
    """
    template = _CONFIG_TEMPLATES.get(kind)
    if template is None:
        raise HTTPException(
            status_code=422,
            detail=f"未知 provider kind: {kind!r}（支持: {sorted(_CONFIG_TEMPLATES)}）")

    # 优先用库内现有同 kind provider 的实际键作为参考
    config_example = None
    with connect() as conn:
        row = conn.execute(
            "SELECT config_json FROM providers WHERE kind = ?"
            " ORDER BY id LIMIT 1", (kind,)).fetchone()
    if row:
        config_example = _parse_json(row["config_json"])

    result = {
        "kind": kind,
        "provider_config_structure": _mask(config_example or template),
    }
    if kind == "qingguo":
        # 历史行为：附青果隧道缓存文件的键结构
        path = Path(proxy_ops.QINGGUO_CACHE_FILE)
        tunnel_cache = None
        try:
            tunnel_cache = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        result.update({
            "tunnel_cache_path": str(path),
            "tunnel_cache_exists": tunnel_cache is not None,
            "tunnel_cache_structure": _mask(tunnel_cache) if tunnel_cache else None,
        })
    return result


# ==================== 写入 ====================

def _provider_or_404(provider_id: int) -> dict:
    provider = proxy_ops.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} 不存在")
    return provider


@router.post("")
def upsert_provider(body: ProviderUpsert):
    pid = proxy_ops.upsert_provider(body.kind, body.name, body.config, body.enabled)
    provider = proxy_ops.get_provider(pid)
    sync = proxy_ops.refresh_channels(provider)
    provider = proxy_ops.get_provider(pid)  # 重新取，带上同步后的 channels
    provider["refresh"] = sync
    return provider


@router.put("/{provider_id}")
def update_provider(provider_id: int, body: ProviderPatch):
    existing = _provider_or_404(provider_id)
    config_changed = (
        body.config is not None
        and body.config != existing.get("config", {})
    )
    ok = proxy_ops.update_provider(
        provider_id, name=body.name, config=body.config, enabled=body.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} 不存在")
    provider = proxy_ops.get_provider(provider_id)
    if config_changed:
        sync = proxy_ops.refresh_channels(provider)
        provider = proxy_ops.get_provider(provider_id)
        provider["refresh"] = sync
    return provider


@router.post("/{provider_id}/probe")
def probe_provider(provider_id: int):
    provider = _provider_or_404(provider_id)
    config = provider.get("config") or {}
    targets = [ch for ch in provider["channels"]
               if ch.get("tunnel") and ch.get("status") not in PROBE_SKIP_STATUSES]
    if not targets:
        return {"ok": 0, "fail": 0, "results": [],
                "note": "没有可探测的通道（空 tunnel 或已 disabled）"}

    workers = min(MAX_PROBE_WORKERS, len(targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda ch: proxy_ops.probe_channel(ch, config),
                                targets))
    ok = sum(1 for r in results if r.get("ok"))
    return {"ok": ok, "fail": len(results) - ok, "results": results}


@router.post("/{provider_id}/channels/refresh")
def refresh_provider_channels(provider_id: int):
    provider = _provider_or_404(provider_id)
    sync = proxy_ops.refresh_channels(provider)
    provider = proxy_ops.get_provider(provider_id)
    provider["refresh"] = sync
    return provider
