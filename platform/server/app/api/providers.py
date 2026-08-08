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

@router.get("")
def list_providers():
    with connect() as conn:
        providers = conn.execute(
            "SELECT * FROM providers ORDER BY id").fetchall()
        channels = conn.execute(
            "SELECT * FROM proxy_channels ORDER BY provider_id, id").fetchall()

    by_provider = {}
    for ch in channels:
        by_provider.setdefault(ch["provider_id"], []).append(dict(ch))

    result = []
    for p in providers:
        item = dict(p)
        item["config_json"] = _parse_json(item.get("config_json"))
        item["proxy_channels"] = by_provider.get(p["id"], [])
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
