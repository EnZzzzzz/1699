# -*- coding: utf-8 -*-
"""WhatsApp 账号登录进程管理器。

通过 `node check.js [--auth=<name>] <占位号码>` 启动 Baileys 会话：
- 未登录时生成二维码（终端 + qr png 文件），手机扫码后连接成功，
  会话写入 auth_info / auth_info-<name>/ 目录；
- 进程连接成功标志：stdout 出现「已连接」。之后查完占位号码自然退出。

进程表保存在内存（服务重启即失效），状态：
waiting_scan -> connected | failed | expired
"""

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

WA_CHECK_DIR = Path(
    "/Volumes/DataDrive/proj/public/1699/fetcher/vendor/wa-check")

# 占位号码：登录场景下连上后查它然后自然退出，会话已落盘
PLACEHOLDER_NUMBER = "8617750013805"

CONNECTED_MARK = "已连接"

# 等待扫码的超时（秒），超过则标记 expired（进程通常仍活着，二维码会刷新）
SCAN_TIMEOUT = 300

_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,20}$")
_tail_lock = threading.Lock()


class LoginError(Exception):
    """业务错误，status 语义由调用方决定。"""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def validate_name(name: str) -> str:
    """校验账号名：字母数字短横，≤20 字符。非法抛 422。"""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise LoginError(
            "账号名需为 1-20 位字母、数字或短横线", status_code=422)
    return name


def auth_dir_for(name: str) -> Path:
    if name == "default":
        return WA_CHECK_DIR / "auth_info"
    return WA_CHECK_DIR / f"auth_info-{name}"


def qr_path_for(name: str) -> Path:
    if name == "default":
        return WA_CHECK_DIR / "qr.png"
    return WA_CHECK_DIR / f"qr-auth_info-{name}.png"


# name -> {"proc", "started_at", "state", "tail", "thread"}
_sessions: dict[str, dict] = {}


def _pump_output(name: str, proc: subprocess.Popen) -> None:
    """后台线程：读 stdout，更新状态，收集尾部输出。"""
    tail: list[str] = []
    sess = _sessions.get(name)
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 50:
                tail = tail[-50:]
            if CONNECTED_MARK in line and sess is not None:
                if sess["state"] in ("waiting_scan", "expired"):
                    sess["state"] = "connected"
    except (ValueError, OSError):
        pass
    finally:
        proc.wait()
        if sess is not None and _sessions.get(name) is sess:
            sess["tail"] = tail
            if sess["state"] in ("waiting_scan", "expired"):
                sess["state"] = "failed"
            # connected 保持不变（进程查完占位号码自然退出）


def start_login(name: str) -> dict:
    """启动登录流程。name=default 用无 --auth 形式。

    冲突（auth dir 已存在即已登录 / 同名进程在跑）抛 409。
    """
    validate_name(name)

    auth_dir = auth_dir_for(name)
    creds = auth_dir / "creds.json"
    if creds.is_file():
        raise LoginError(f"账号 {name!r} 已登录（{auth_dir.name} 已存在），"
                         "如需重新登录请先删除", status_code=409)

    sess = _sessions.get(name)
    if sess and sess["proc"].poll() is None:
        raise LoginError(f"账号 {name!r} 已有登录流程进行中", status_code=409)

    cmd = ["node", "check.js"]
    if name != "default":
        cmd.append(f"--auth={name}")
    cmd.append(PLACEHOLDER_NUMBER)

    proc = subprocess.Popen(
        cmd,
        cwd=str(WA_CHECK_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    sess = {
        "proc": proc,
        "started_at": time.time(),
        "state": "waiting_scan",
        "tail": [],
    }
    _sessions[name] = sess
    t = threading.Thread(target=_pump_output, args=(name, proc), daemon=True)
    sess["thread"] = t
    t.start()
    return {"ok": True, "name": name, "state": sess["state"]}


def get_state(name: str) -> dict:
    """返回登录状态快照；无进行中的流程则按 auth dir 推断。"""
    sess = _sessions.get(name)
    if sess and sess["proc"].poll() is None:
        # 等待扫码超时标记 expired（二维码仍在刷新，可继续扫）
        if (sess["state"] == "waiting_scan"
                and time.time() - sess["started_at"] > SCAN_TIMEOUT):
            sess["state"] = "expired"
        return {
            "name": name,
            "state": sess["state"],
            "started_at": sess["started_at"],
        }
    if sess:
        return {
            "name": name,
            "state": sess["state"],
            "started_at": sess["started_at"],
            "tail": sess.get("tail", [])[-10:],
        }
    # 无内存记录：已登录则视为 connected，否则未开始
    if (auth_dir_for(name) / "creds.json").is_file():
        return {"name": name, "state": "connected", "started_at": None}
    return {"name": name, "state": "idle", "started_at": None}


def get_qr(name: str) -> tuple[Path, float | None]:
    """返回 (qr 文件路径, mtime epoch 或 None)。"""
    p = qr_path_for(name)
    if p.is_file():
        return p, p.stat().st_mtime
    return p, None


def pump_thread_alive(name: str) -> bool:
    sess = _sessions.get(name)
    t = sess.get("thread") if sess else None
    return bool(t and t.is_alive())


def cancel_login(name: str) -> bool:
    """terminate 登录进程；返回是否有进程被取消。"""
    sess = _sessions.get(name)
    if not sess:
        return False
    proc = sess["proc"]
    cancelled = proc.poll() is None
    if cancelled:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if sess["state"] in ("waiting_scan", "expired"):
        sess["state"] = "failed"
        sess["tail"] = sess.get("tail", []) + ["已取消"]
    return cancelled


def delete_account(name: str) -> dict:
    """删除账号：先 cancel 登录进程，再删 auth dir 与该账号 qr 文件。"""
    validate_name(name)
    cancel_login(name)
    removed = []
    auth_dir = auth_dir_for(name)
    if auth_dir.is_dir():
        shutil.rmtree(auth_dir, ignore_errors=True)
        removed.append(auth_dir.name)
    qr = qr_path_for(name)
    if qr.is_file():
        try:
            qr.unlink()
            removed.append(qr.name)
        except OSError:
            pass
    _sessions.pop(name, None)
    return {"ok": True, "name": name, "removed": removed}
