# -*- coding: utf-8 -*-
"""新增 4 表的 ORM 模型（docs/service-architecture.md §4）。

现有 5 表（crawl_runs/shops/contacts/category_progress/cookies）不在此建 ORM，
统计类查询走原生 SQL（见 api/stats.py），避免与 scraper 侧的建表逻辑双写漂移。
"""
from __future__ import annotations

import json

from sqlalchemy import Column, Integer, Text

from .db import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    config_json = Column(Text, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    @property
    def config(self) -> dict:
        return json.loads(self.config_json)

    def to_dict(self, mask_secrets: bool = True) -> dict:
        cfg = self.config
        if mask_secrets:
            # 界面上密码字段掩码显示（docs §4 备注）
            cfg = {k: ("********" if "pwd" in k.lower() or "secret" in k.lower() else v)
                   for k, v in cfg.items()}
        return {
            "id": self.id, "kind": self.kind, "name": self.name,
            "config": cfg, "enabled": bool(self.enabled),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class ProxyChannel(Base):
    __tablename__ = "proxy_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, nullable=True)   # NULL = 直连（本机 IP）
    tunnel = Column(Text, nullable=True)
    exit_ip = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="idle")  # idle / in_use / error
    used_by_task = Column(Integer, nullable=True)
    ip_expires_at = Column(Text, nullable=True)
    last_probe_at = Column(Text, nullable=True)

    @property
    def is_direct(self) -> bool:
        return self.provider_id is None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "provider_id": self.provider_id,
            "is_direct": self.is_direct,
            "tunnel": self.tunnel, "exit_ip": self.exit_ip,
            "status": self.status, "used_by_task": self.used_by_task,
            "ip_expires_at": self.ip_expires_at, "last_probe_at": self.last_probe_at,
        }


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(Text, nullable=False)            # shop_crawl / contact_fetch
    params_json = Column(Text, nullable=False)
    celery_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending")
    progress_json = Column(Text, nullable=True)
    stop_requested = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    started_at = Column(Text, nullable=True)
    finished_at = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type,
            "params": json.loads(self.params_json),
            "celery_id": self.celery_id, "status": self.status,
            "progress": json.loads(self.progress_json) if self.progress_json else None,
            "stop_requested": bool(self.stop_requested), "error": self.error,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ProxyUsageEvent(Base):
    __tablename__ = "proxy_usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, nullable=False)
    task_id = Column(Integer, nullable=True)
    task_type = Column(Text, nullable=True)
    exit_ip = Column(Text, nullable=True)
    result = Column(Text, nullable=True)           # ok / blocked / error
    ts = Column(Text, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "channel_id": self.channel_id, "task_id": self.task_id,
            "task_type": self.task_type, "exit_ip": self.exit_ip,
            "result": self.result, "ts": self.ts,
        }


class TaskEvent(Base):
    __tablename__ = "task_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False)
    ts = Column(Text, nullable=False)
    level = Column(Text, nullable=False)           # info / success / warning / error
    message = Column(Text, nullable=False)
    data_json = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "ts": self.ts, "level": self.level,
            "message": self.message,
            "data": json.loads(self.data_json) if self.data_json else None,
        }
