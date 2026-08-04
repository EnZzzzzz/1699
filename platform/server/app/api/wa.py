# -*- coding: utf-8 -*-
"""WhatsApp 账号扫描：读取 wa-check 下的 auth_info / auth_info-* 目录。"""

import json
import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/wa")

WA_CHECK_DIR = Path(
    "/Volumes/DataDrive/proj/public/1699/fetcher/vendor/wa-check")


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
