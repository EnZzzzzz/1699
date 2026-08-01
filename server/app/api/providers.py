# -*- coding: utf-8 -*-
"""厂商配置 CRUD / 连通性测试 / 通道校准（docs/service-architecture.md §8）。"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config as app_config
from ..db import get_db
from ..models import Provider, ProxyChannel
from ..services.proxy import PROVIDER_REGISTRY, get_provider
from ..services.proxy.base import ProviderAPIError, ProviderConfigError

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderIn(BaseModel):
    kind: str
    name: str
    config: dict


class ProviderUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


@router.get("/kinds")
def list_kinds():
    """已注册的 provider 类型及其 config_schema（前端动态渲染表单用）。"""
    return {kind: {"kind": cls.kind, "config_schema": cls.config_schema}
            for kind, cls in PROVIDER_REGISTRY.items()}


@router.get("")
def list_providers(db: Session = Depends(get_db)):
    rows = db.query(Provider).order_by(Provider.id).all()
    return [p.to_dict(mask_secrets=True) for p in rows]


@router.post("", status_code=201)
def create_provider(body: ProviderIn, db: Session = Depends(get_db)):
    try:
        provider = get_provider(body.kind)   # 未知 kind 在此抛错
        provider.validate(body.config)
    except ProviderConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    now = app_config.now_str()
    p = Provider(kind=body.kind, name=body.name,
                 config_json=json.dumps(body.config, ensure_ascii=False),
                 enabled=1, created_at=now, updated_at=now)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.to_dict(mask_secrets=True)


@router.put("/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdate, db: Session = Depends(get_db)):
    p = db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    if body.config is not None:
        try:
            get_provider(p.kind).validate(body.config)
        except ProviderConfigError as e:
            raise HTTPException(status_code=400, detail=str(e))
        p.config_json = json.dumps(body.config, ensure_ascii=False)
    if body.name is not None:
        p.name = body.name
    if body.enabled is not None:
        p.enabled = 1 if body.enabled else 0
    p.updated_at = app_config.now_str()
    db.commit()
    return p.to_dict(mask_secrets=True)


@router.delete("/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    in_use = (db.query(ProxyChannel)
              .filter(ProxyChannel.provider_id == provider_id,
                      ProxyChannel.status == "in_use").count())
    if in_use:
        raise HTTPException(status_code=409,
                            detail=f"该厂商有 {in_use} 条通道正在使用，不能删除")
    db.query(ProxyChannel).filter(ProxyChannel.provider_id == provider_id).delete()
    db.delete(p)
    db.commit()
    return {"deleted": provider_id}


@router.post("/{provider_id}/test")
def test_provider(provider_id: int, db: Session = Depends(get_db)):
    """连通性测试：{ok, message?, channels?, exit_ip?, latency_ms?}（前端契约）。

    通道配额 + 校准隧道 + 逐通道探测出口 IP（以库中隧道为缓存）。
    厂商 API/网络错误不抛 5xx，统一以 ok=false + message 返回（测试按钮语义）。
    """
    p = db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    provider = get_provider(p.kind)
    cached = [r[0] for r in db.query(ProxyChannel.tunnel)
              .filter(ProxyChannel.provider_id == provider_id,
                      ProxyChannel.tunnel.isnot(None)).all()]
    started = time.monotonic()
    try:
        result = provider.test_connectivity(p.config, cached=cached)
    except (ProviderAPIError, ProviderConfigError) as e:
        return {"ok": False,
                "message": f"{e} (code={getattr(e, 'code', None)})",
                "latency_ms": round((time.monotonic() - started) * 1000)}
    latency_ms = round((time.monotonic() - started) * 1000)
    probes = result.get("probes") or []
    first_ok = next((pr for pr in probes if pr.get("ok")), None)
    ok = result.get("ok", False)
    return {
        "ok": ok,
        "message": None if ok else "部分或全部通道探测失败",
        "channels": result.get("channel_count"),
        "exit_ip": first_ok.get("exit_ip") if first_ok else None,
        "latency_ms": latency_ms,
        "quota": result.get("quota"),
        "probes": probes,
    }


@router.post("/{provider_id}/sync")
def sync_provider(provider_id: int, db: Session = Depends(get_db)):
    """校准通道列表（cached -> /query -> /get 补齐），新隧道 upsert 进 proxy_channels。"""
    p = db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    provider = get_provider(p.kind)
    cached = [r[0] for r in db.query(ProxyChannel.tunnel)
              .filter(ProxyChannel.provider_id == provider_id,
                      ProxyChannel.tunnel.isnot(None)).all()]
    try:
        channels = provider.sync_channels(p.config, cached=cached)
    except (ProviderAPIError, ProviderConfigError) as e:
        raise HTTPException(status_code=502, detail={
            "error": str(e), "code": getattr(e, "code", None),
            "request_id": getattr(e, "request_id", None)})

    existing = {r[0] for r in db.query(ProxyChannel.tunnel)
                .filter(ProxyChannel.provider_id == provider_id,
                        ProxyChannel.tunnel.isnot(None)).all()}
    added = 0
    for ch in channels:
        if ch.tunnel not in existing:
            db.add(ProxyChannel(provider_id=provider_id, tunnel=ch.tunnel,
                                exit_ip=ch.exit_ip, status="idle"))
            added += 1
    db.commit()
    return {"provider_id": provider_id, "synced": len(channels), "added": added,
            "tunnels": [c.tunnel for c in channels]}
