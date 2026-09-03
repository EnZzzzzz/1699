#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wx_lookup_runner.py — fb_contacts 微信查号跑批（平台 /scripts 页「微信查号」脚本）。

从 fb_contacts 取未查（wx_registered IS NULL）的中国手机号，逐号调本机
wxserver（chatbot 子仓 tools/wxserver.py，HTTP 127.0.0.1:19002）查陌生人
微信信息，结果写回 fb_contacts 的 wx_* 列，头像下载到 .cache/wx_avatars/。

依赖与边界：
- wxserver 生命周期不归本脚本管（launchctl 服务 com.wechatbot.wxserver，
  当前从原始克隆 /Volumes/DataDrive/proj/my/WeChatBot 启动；子仓 chatbot/tmp
  是私有备份不入库）。预检连不上/无在线账号直接 exit 1。
- UI 自动化会抢微信窗口焦点，运行期间勿操作键鼠；微信有搜索频控，
  --interval 默认 3 秒，连续 5 个 error 判定频控熔断退出（exit 2），
  避免大规模误标 wx_registered=0。
- error 含「未找到」才标 0（未注册/禁止被搜索）；其他异常保持 NULL 下轮重查。

用法：
    python3 platform/server/wx_lookup_runner.py [--interval 3] [--limit 0] [--port 19002]
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

# 项目根（platform/server/wx_lookup_runner.py 上溯 2 级）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT, ".cache", "1688.db")
AVATAR_DIR = os.path.join(ROOT, ".cache", "wx_avatars")

BATCH = 100               # 每轮取号数
MAX_CONSEC_ERRORS = 5     # 连续 error 熔断阈值（频控保护）

# 性别映射：wxserver 返回 男/女/未知 → 与 wa_gender 同口径
GENDER_MAP = {"男": "male", "女": "female"}


def _bj_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _http(method: str, url: str, body: dict = None, timeout: float = 30):
    """urllib 极简 JSON 客户端，返回 (status, obj)；网络层异常抛 urllib.error。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def preflight(port: int) -> bool:
    """检查 wxserver 可达且有在线账号。"""
    try:
        status, obj = _http("GET", f"http://127.0.0.1:{port}/accounts", timeout=5)
    except (urllib.error.URLError, OSError) as e:
        print(f"[预检失败] wxserver 连不上（127.0.0.1:{port}）：{e}\n"
              "wxserver 是 launchctl 服务 com.wechatbot.wxserver"
              "（源自 /Volumes/DataDrive/proj/my/WeChatBot），请先确认它已启动",
              flush=True)
        return False
    if status != 200:
        print(f"[预检失败] wxserver /accounts 返回 {status}", flush=True)
        return False
    if not obj.get("online"):
        print("[预检失败] wxserver 无在线账号（微信进程未运行或密钥缺失）", flush=True)
        return False
    names = [a["name"] for a in obj.get("accounts", []) if a.get("online")]
    print(f"[预检通过] wxserver 在线账号：{', '.join(names)}", flush=True)
    return True


def fetch_batch(limit: int, exclude: frozenset = frozenset()):
    """取一批未查号码（wx_registered IS NULL，裸 11 位中国手机号）。

    exclude 排除本轮已失败的 id——失败号保持 NULL，不排除会被反复取到
    造成死循环。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fb_contacts)")}
        if "wx_registered" not in cols:
            print("[错误] fb_contacts 缺 wx_registered 列，请先重启平台后端跑 migrate",
                  flush=True)
            sys.exit(1)
        sql = ("SELECT id, number FROM fb_contacts"
               " WHERE wx_registered IS NULL AND length(number) = 11")
        params: list = []
        if exclude:
            marks = ",".join("?" * len(exclude))
            sql += f" AND id NOT IN ({marks})"
            params.extend(sorted(exclude))
        sql += " ORDER BY id LIMIT ?"
        params.append(limit if limit > 0 else BATCH)
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def save_result(cid: int, registered: int, row: dict = None):
    """单号结果落库（短事务）。registered=1 时带画像字段。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        now = _bj_now()
        if registered == 1 and row:
            conn.execute(
                "UPDATE fb_contacts SET wx_registered=1, wx_checked_at=?,"
                " wx_username=?, wx_nick=?, wx_gender=?, wx_avatar=? WHERE id=?",
                (now, row.get("username") or None, row.get("nick_name") or None,
                 GENDER_MAP.get(row.get("gender"), "unknown"),
                 row.get("avatar_file"), cid))
        else:
            conn.execute(
                "UPDATE fb_contacts SET wx_registered=?, wx_checked_at=? WHERE id=?",
                (registered, now, cid))
        conn.commit()
    finally:
        conn.close()


def download_avatar(number: str, row: dict) -> str:
    """下载头像到 .cache/wx_avatars/<number>.jpg，成功返回文件名，失败 None。"""
    url = row.get("big_head_url") or row.get("small_head_url")
    if not url:
        return None
    os.makedirs(AVATAR_DIR, exist_ok=True)
    fname = f"{number}.jpg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp, \
                open(os.path.join(AVATAR_DIR, fname), "wb") as f:
            f.write(resp.read())
        return fname
    except Exception as e:  # noqa: BLE001 - 头像失败不阻塞主流程
        print(f"  [头像下载失败] {number}: {e}", flush=True)
        return None


def main():
    ap = argparse.ArgumentParser(description="fb_contacts 微信查号跑批")
    ap.add_argument("--interval", type=float, default=3.0,
                    help="号间隔秒数（防频控，默认 3）")
    ap.add_argument("--limit", type=int, default=0,
                    help="本轮最多查多少个（默认 0=查到清空为止）")
    ap.add_argument("--port", type=int, default=19002, help="wxserver 端口")
    args = ap.parse_args()

    if not preflight(args.port):
        sys.exit(1)

    done = ok = not_found = failed = consec_err = 0
    failed_ids: set = set()
    while True:
        remaining = args.limit - done if args.limit > 0 else BATCH
        if remaining <= 0:
            break
        rows = fetch_batch(min(remaining, BATCH) if args.limit > 0 else BATCH,
                           exclude=frozenset(failed_ids))
        if not rows:
            break
        for cid, number in rows:
            try:
                status, r = _http("POST", f"http://127.0.0.1:{args.port}/lookup",
                                  {"phone": number}, timeout=30)
            except (urllib.error.URLError, OSError) as e:
                r, status = {"error": f"请求异常: {e}"}, 0
            if status == 200 and "error" not in r:
                consec_err = 0
                r["avatar_file"] = download_avatar(number, r)
                save_result(cid, 1, r)
                ok += 1
                print(f"[{done + 1}] {number} -> {r.get('nick_name') or '?'}"
                      f" ({r.get('gender') or '未知'})"
                      f"{' 有头像' if r['avatar_file'] else ''}", flush=True)
            else:
                err = r.get("error", f"HTTP {status}")
                consec_err += 1
                if "未找到" in err:
                    save_result(cid, 0)
                    not_found += 1
                    print(f"[{done + 1}] {number} -> 无微信", flush=True)
                else:
                    failed += 1
                    failed_ids.add(cid)
                    print(f"[{done + 1}] {number} -> 失败（保持未查）: {err}",
                          flush=True)
                if consec_err >= MAX_CONSEC_ERRORS:
                    print(f"[熔断] 连续 {MAX_CONSEC_ERRORS} 个 error，"
                          "疑似触发微信频控，退出；请稍后重启脚本续跑", flush=True)
                    sys.exit(2)
            done += 1
            time.sleep(args.interval)

    print(f"[完成] 本轮查 {done} 个：有微信 {ok} / 无微信 {not_found} / 失败 {failed}",
          flush=True)


if __name__ == "__main__":
    main()
