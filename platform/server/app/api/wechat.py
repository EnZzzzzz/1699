# -*- coding: utf-8 -*-
"""微信在线状态接口。

数据来源：chatbot 子仓（chatbot/tools/wxaccounts.py）的容器扫描，
online = 微信进程在跑且 db_dir 存在。30 秒缓存（扫描要起 PlistBuddy/pgrep
子进程，避免前端高频刷新反复扫）。只读调用（write_config=False），
不会改写 ~/.wechat-cli/ 下的账号配置。
"""

import importlib.util
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/wechat")

TZ = ZoneInfo("Asia/Shanghai")

# 项目根目录下的 chatbot 子仓（git submodule: EnZzzzzz/ChatBot）
WXACCOUNTS_PATH = (Path(__file__).resolve().parents[4]
                   / "chatbot" / "tools" / "wxaccounts.py")

CACHE_TTL = 30  # 秒
_cache: dict = {"ts": 0.0, "data": None}
_lock = threading.Lock()


def _load_wxaccounts():
    if not WXACCOUNTS_PATH.exists():
        raise HTTPException(
            503, f"chatbot 子仓缺失：{WXACCOUNTS_PATH}（先 git submodule update --init）")
    spec = importlib.util.spec_from_file_location("wxaccounts", WXACCOUNTS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scan():
    """扫描微信账号，返回 {ts, online, total, accounts}；带 30s 缓存。"""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["ts"] < CACHE_TTL:
            return _cache["data"]
        mod = _load_wxaccounts()
        accounts = [
            {
                "name": a["name"],
                "wxid": a["wxid"],
                "online": a["online"],
                "keys_ok": a["keys_ok"],
                "pid": a["pid"],
            }
            for a in mod.discover(write_config=False)
        ]
        data = {
            "ts": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "online": sum(1 for a in accounts if a["online"]),
            "total": len(accounts),
            "accounts": accounts,
        }
        _cache.update(ts=time.time(), data=data)
        return data


@router.get("/status")
def status():
    """微信在线状态：online 个 / total 个账号，附逐账号明细。"""
    try:
        return _scan()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - 扫描环境异常统一吐 503
        raise HTTPException(503, f"微信状态扫描失败：{e}")
