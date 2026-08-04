# -*- coding: utf-8 -*-
"""WhatsApp 账号管理：扫描 auth_info 目录 + 扫码登录流程 API。"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import wa_login

router = APIRouter(prefix="/wa")

WA_CHECK_DIR = wa_login.WA_CHECK_DIR


def _read_account(auth_dir: Path, name: str) -> dict:
    creds_file = auth_dir / "creds.json"
    logged_in = False
    phone = None
    if creds_file.is_file():
        try:
            creds = json.loads(creds_file.read_text(encoding="utf-8"))
            me = creds.get("me") or {}
            me_id = me.get("id")
            if me_id:
                logged_in = True
                # me.id 形如 "8617750013805:4@s.whatsapp.net"，取纯数字部分
                m = re.match(r"(\d+)", me_id)
                phone = m.group(1) if m else None
        except (ValueError, OSError):
            pass
    return {
        "name": name,
        "auth_dir": str(auth_dir),
        "logged_in": logged_in,
        "phone": phone,
    }


@router.get("/accounts")
def list_accounts():
    accounts = []
    if WA_CHECK_DIR.is_dir():
        for entry in sorted(WA_CHECK_DIR.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name == "auth_info":
                accounts.append(_read_account(entry, "default"))
            elif entry.name.startswith("auth_info-"):
                accounts.append(_read_account(
                    entry, entry.name[len("auth_info-"):]))
    return accounts


class LoginStartBody(BaseModel):
    name: str


@router.post("/accounts", status_code=201)
def start_login(body: LoginStartBody):
    """启动扫码登录流程；非法名字 422，冲突（已登录/进行中）409。"""
    try:
        return wa_login.start_login(body.name)
    except wa_login.LoginError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/accounts/{name}/login")
def login_status(name: str):
    """登录状态 + 二维码信息（前端按 mtime 变化轮询刷新）。"""
    try:
        wa_login.validate_name(name)
    except wa_login.LoginError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    st = wa_login.get_state(name)
    _, mtime = wa_login.get_qr(name)
    return {
        "name": name,
        "state": st["state"],
        "started_at": st["started_at"],
        "tail": st.get("tail", []),
        "qr_url": (f"/api/wa/accounts/{name}/qr?t={int(mtime)}"
                   if mtime is not None else None),
        "qr_mtime": mtime,
        "pump_alive": wa_login.pump_thread_alive(name),
    }


@router.get("/accounts/{name}/qr")
def login_qr(name: str):
    """返回二维码 png（无文件 404）。"""
    try:
        wa_login.validate_name(name)
    except wa_login.LoginError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    p, mtime = wa_login.get_qr(name)
    if mtime is None:
        raise HTTPException(status_code=404, detail="二维码尚未生成")
    return FileResponse(str(p), media_type="image/png")


@router.delete("/accounts/{name}")
def delete_account(name: str):
    """删除账号（auth dir + qr 文件），先 cancel 进行中的登录进程。"""
    try:
        return wa_login.delete_account(name)
    except wa_login.LoginError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
