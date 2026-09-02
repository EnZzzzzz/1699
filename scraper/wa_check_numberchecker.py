# -*- coding: utf-8 -*-
"""wa_check_numberchecker.py — 用 numberchecker.ai 批量查 us_contacts 的 WhatsApp 注册态。

背景（2026-09-02 接入）：numberchecker.ai 是文件任务制 API（$1/万号，
约为 Apify devscrapper $0.004/号 的 1/40），但实测两条硬限制：
- 不支持 +86 中国大陆号（API 直接报 china_mainland_not_supported），
  因此 fb_contacts 主池查不了，本脚本只服务领英美国线的 us_contacts；
- 单任务去重+有效性校验后最少 500 号，不足直接拒收——默认
  --min-batch 500 攒批开火。
流程：POST /v1/tasks 上传 txt（每行一个 E.164 号，task_type=ws）→
POST /v1/gettasks 轮询到 status=exported → 下载 result_url（zip 内
<task_id>/all.csv，列 number,activated，yes/no，number 不带 + 号）。
文档：https://docs.numberchecker.ai/ ；key 存 providers 表（kind=numberchecker）。

用法：
    python3 scraper/wa_check_numberchecker.py                # 待查号 ≥500 才开火
    python3 scraper/wa_check_numberchecker.py --limit 1000   # 限量
    python3 scraper/wa_check_numberchecker.py --dry-run      # 只列号不调 API
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".cache" / "1688.db"
STATE_PATH = REPO_ROOT / ".cache" / "wa_check_numberchecker_state.json"
API = "https://api.numberchecker.ai/v1"

COST_PER_NUMBER = 0.0001   # 官方定价 $1.00/万号（pricing 页 WhatsApp Bulk Checker）
PLATFORM_MIN_BATCH = 500   # 平台硬限制：去重+有效性校验后不足 500 拒收
TASK_CHUNK = 10000         # 单任务号数上限（平台允许 100 万，分批控制单批损失）
POLL_INTERVAL = 15         # gettasks 轮询间隔（秒）；实测 530 号约 15s 出结果
POLL_TIMEOUT = 3600        # 单任务轮询总超时（秒）


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_number(number: str) -> str | None:
    """送检前归一化为 E.164（带 +）。us_contacts 库存归一化 11 位
    1XXXXXXXXXX（+1 北美号）；NANP 区号第二位须 2-9，不满足直接拒送
    （返回 None，调用方标 invalid 不浪费额度）。"""
    d = re.sub(r"\D+", "", number or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 10 and d[0] in "23456789":
        d = "1" + d
    if not re.match(r"1[2-9]\d{9}$", d):
        return None
    return "+" + d


def load_api_key(conn: sqlite3.Connection) -> str:
    """取最新一个启用中的 numberchecker 账号 api_key。"""
    rows = conn.execute(
        "SELECT name, config_json FROM providers"
        " WHERE kind='numberchecker' AND enabled=1 ORDER BY id DESC").fetchall()
    for name, cfg in rows:
        key = (json.loads(cfg) or {}).get("api_key")
        if key:
            log(f"使用 numberchecker 账号：{name}")
            return key
    sys.exit("[!] providers 表无 enabled 且配置了 api_key 的 numberchecker 账号")


def get_balance(api_key: str) -> float:
    req = urllib.request.Request(f"{API}/balance",
                                 headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return float(json.loads(resp.read().decode())["balance"])


def _post_form(api_key: str, path: str, fields: dict[str, str],
               file_path: Path | None = None) -> dict:
    """multipart/form-data POST（平台提交/查询接口均为 form 形态）。"""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data;'
                     f' name="{k}"\r\n\r\n{v}\r\n'.encode())
    if file_path is not None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file";'
            f' filename="{file_path.name}"\r\n'
            f'Content-Type: text/plain\r\n\r\n'.encode()
            + file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        API + path, data=b"".join(parts),
        headers={"X-API-Key": api_key,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def submit_task(api_key: str, numbers: list[str], workdir: Path) -> str:
    """上传号码文件建任务，返回 task_id。"""
    f = workdir / f"nc_{int(time.time())}.txt"
    f.write_text("\n".join(numbers) + "\n")
    try:
        resp = _post_form(api_key, "/tasks", {"task_type": "ws"}, f)
    finally:
        f.unlink(missing_ok=True)
    task_id = resp.get("task_id")
    if not task_id:
        raise RuntimeError(f"建任务失败：{resp}")
    log(f"  任务 {task_id} 已创建（{resp.get('total')} 号，预估 "
        f"${(resp.get('estimated_amount') or {}).get('amount')}）")
    return task_id


def wait_result(api_key: str, task_id: str) -> str:
    """轮询任务直到 exported，返回 result_url。"""
    t0 = time.time()
    while True:
        resp = _post_form(api_key, "/gettasks", {"task_id": task_id})
        status = resp.get("status")
        if status == "exported" and resp.get("result_url"):
            return resp["result_url"]
        if status not in ("pending", "processing"):
            raise RuntimeError(f"任务 {task_id} 异常状态：{resp}")
        if time.time() - t0 > POLL_TIMEOUT:
            raise RuntimeError(f"任务 {task_id} 轮询超时（{POLL_TIMEOUT}s）")
        time.sleep(POLL_INTERVAL)


def download_activated(result_url: str) -> dict[str, bool]:
    """下载结果 zip，解析 all.csv → {裸数字号: 是否注册}。"""
    with urllib.request.urlopen(result_url, timeout=300) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.endswith("all.csv"))
        text = zf.read(name).decode("utf-8-sig")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        d = re.sub(r"\D+", "", row.get("number", ""))
        if d:
            out[d] = (row.get("activated") or "").strip().lower() == "yes"
    return out


def record_daily(n: int) -> None:
    """按北京日期累计已查号数到 state JSON（平台费用估算行读这里）。"""
    state = {}
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        pass
    daily = state.setdefault("daily", {})
    day = time.strftime("%Y-%m-%d")
    daily[day] = daily.get(day, 0) + n
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="numberchecker.ai 批量查 us_contacts WA 注册态")
    ap.add_argument("--limit", type=int, default=0, help="最多查多少个（缺省不限）")
    ap.add_argument("--min-batch", type=int, default=PLATFORM_MIN_BATCH,
                    help=f"待查号少于此数不开火（平台硬下限 {PLATFORM_MIN_BATCH}，缺省同）")
    ap.add_argument("--dry-run", action="store_true", help="只列号不调 API")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    api_key = load_api_key(conn)

    # 待查口径：wa_registered IS NULL 且未被标 invalid（无效号永远查不出）
    rows = conn.execute(
        "SELECT id, number FROM us_contacts"
        " WHERE wa_registered IS NULL"
        " AND (wa_source IS NULL OR wa_source != 'invalid') ORDER BY id").fetchall()
    if args.limit:
        rows = rows[:args.limit]
    # 归一化为 E.164；号段明显不可能的直接标 invalid，不浪费额度
    send_rows, pre_inv = [], 0
    ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
    for row_id, number in rows:
        norm = normalize_number(number)
        if norm is None:
            conn.execute("UPDATE us_contacts SET wa_checked_at=?,"
                         " wa_source='invalid' WHERE id=?", (ts_now, row_id))
            pre_inv += 1
        else:
            send_rows.append((row_id, number, norm))
    if pre_inv:
        conn.commit()
        log(f"号段预过滤：{pre_inv} 个明显无效号直接标记（未调 API）")
    log(f"us_contacts 待查号 {len(send_rows)} 个，"
        f"预估费用 ${len(send_rows) * COST_PER_NUMBER:.4f}")
    if len(send_rows) < args.min_batch:
        log(f"不足 --min-batch {args.min_batch}，攒批中本轮不开火")
        return 0
    if not send_rows or args.dry_run:
        for _, n, norm in send_rows:
            print(" ", n, "->", norm)
        return 0

    balance = get_balance(api_key)
    cost = len(send_rows) * COST_PER_NUMBER
    log(f"账户余额 ${balance:.2f}，本轮预估 ${cost:.4f}")
    if balance < cost:
        log("[!] 余额不足，本轮不开火")
        return 0

    t0 = time.time()
    tot = {"reg": 0, "not": 0, "err": 0, "wb": 0}
    for i in range(0, len(send_rows), TASK_CHUNK):
        chunk = send_rows[i:i + TASK_CHUNK]
        try:
            task_id = submit_task(api_key, [r[2] for r in chunk],
                                  REPO_ROOT / ".cache")
            result = download_activated(wait_result(api_key, task_id))
        except Exception as e:  # noqa: BLE001
            # 单批失败不中断整轮：跳过该块（未回写的号下轮自动补查）
            log(f"  第 {i // TASK_CHUNK + 1} 批失败跳过"
                f"（{type(e).__name__}: {e}），下轮补查")
            continue
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        chunk_err = 0
        for row_id, number, norm in chunk:
            # 结果 csv 的 number 不带 +，与库内裸数字形态一致，直接匹配；
            # activated=False 也是有效结果，不能用 or 链判空
            activated = result.get(number)
            if activated is None:
                activated = result.get(norm.lstrip("+"))
            if activated is None:
                tot["err"] += 1
                chunk_err += 1
                continue
            reg = 1 if activated else 0
            cur = conn.execute(
                "UPDATE us_contacts SET wa_registered=?, wa_checked_at=?,"
                " wa_source='checked' WHERE id=?", (reg, ts, row_id))
            tot["wb"] += cur.rowcount
            tot["reg"] += reg
            tot["not"] += (1 - reg)
        conn.commit()
        record_daily(len(chunk) - chunk_err)
        log(f"  已查 {min(i + TASK_CHUNK, len(send_rows))}/{len(send_rows)}"
            f"（{time.time() - t0:.0f}s，已注册 {tot['reg']}）")
    rate = tot["reg"] / (tot["reg"] + tot["not"]) * 100 if (tot["reg"] + tot["not"]) else 0
    log(f"回写 {tot['wb']} 行：已注册 {tot['reg']}，未注册 {tot['not']}，"
        f"查询失败 {tot['err']}——注册率 {rate:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
