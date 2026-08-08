# -*- coding: utf-8 -*-
"""WhatsApp 账号登录进程管理器。

通过 `node check.js [--auth=<name>] [--pairing=<手机号>] <占位号码>` 启动 Baileys 会话：
- 扫码方式（默认）：未登录时生成二维码（终端 + qr png 文件），手机扫码后连接成功；
- 配对码方式（method="pairing"）：check.js 请求 8 位配对码并落盘 pairing txt 文件，
  手机在「已链接的设备 → 关联设备 → 改用电话号码」输入完成登录；
- 两种方式登录成功后会话都写入 auth_info / auth_info-<name>/ 目录；
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
# 配对码登录的手机号：带国家码纯数字 8-15 位（与原子层 normalize_numbers 口径一致）
_PHONE_RE = re.compile(r"^\d{8,15}$")
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


def pairing_path_for(name: str) -> Path:
    """配对码文件（check.js pairing 模式落盘，命名规则与 qr 文件一致）。"""
    if name == "default":
        return WA_CHECK_DIR / "pairing.txt"
    return WA_CHECK_DIR / f"pairing-auth_info-{name}.txt"


def validate_pairing_phone(phone: str) -> str:
    """校验配对码登录的手机号：带国家码纯数字 8-15 位。非法抛 422。"""
    if not isinstance(phone, str) or not _PHONE_RE.match(phone):
        raise LoginError(
            "配对码登录需提供带国家码的纯数字手机号（8-15 位），"
            "如 8613800138000", status_code=422)
    return phone


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


def start_login(name: str, method: str = "qr", phone: str | None = None) -> dict:
    """启动登录流程。name=default 用无 --auth 形式。

    method: "qr"（扫码，默认）| "pairing"（手机号配对码，phone 必填）。
    冲突（auth dir 已存在即已登录 / 同名进程在跑）抛 409。
    """
    validate_name(name)
    if method not in ("qr", "pairing"):
        raise LoginError(f"未知登录方式: {method!r}", status_code=422)
    if method == "pairing":
        validate_pairing_phone(phone)

    auth_dir = auth_dir_for(name)
    creds = auth_dir / "creds.json"
    if creds.is_file():
        raise LoginError(f"账号 {name!r} 已登录（{auth_dir.name} 已存在），"
                         "如需重新登录请先删除", status_code=409)

    sess = _sessions.get(name)
    if sess and sess["proc"].poll() is None:
        raise LoginError(f"账号 {name!r} 已有登录流程进行中", status_code=409)

    # pairing 模式：清掉旧配对码文件，防止前端读到上一次流程的串码
    if method == "pairing":
        try:
            pairing_path_for(name).unlink(missing_ok=True)
        except OSError:
            pass

    cmd = ["node", "check.js"]
    if name != "default":
        cmd.append(f"--auth={name}")
    if method == "pairing":
        cmd.append(f"--pairing={phone}")
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
        "method": method,
        "tail": [],
    }
    _sessions[name] = sess
    t = threading.Thread(target=_pump_output, args=(name, proc), daemon=True)
    sess["thread"] = t
    t.start()
    return {"ok": True, "name": name, "state": sess["state"], "method": method}


def get_state(name: str) -> dict:
    """返回登录状态快照；无进行中的流程则按 auth dir 推断。

    附带 method（登录方式，无记录时 None）与 pairing_code（仅 pairing
    方式且 check.js 已产出配对码文件时有值，读文件而非解析 stdout）。
    """
    method = None
    sess = _sessions.get(name)
    if sess:
        method = sess.get("method")
        if sess["proc"].poll() is None:
            # 等待扫码超时标记 expired（二维码仍在刷新，可继续扫）
            if (sess["state"] == "waiting_scan"
                    and time.time() - sess["started_at"] > SCAN_TIMEOUT):
                sess["state"] = "expired"
            st = {
                "name": name,
                "state": sess["state"],
                "started_at": sess["started_at"],
            }
        else:
            st = {
                "name": name,
                "state": sess["state"],
                "started_at": sess["started_at"],
                "tail": sess.get("tail", [])[-10:],
            }
    else:
        # 无内存记录：已登录则视为 connected，否则未开始
        if (auth_dir_for(name) / "creds.json").is_file():
            st = {"name": name, "state": "connected", "started_at": None}
        else:
            st = {"name": name, "state": "idle", "started_at": None}
    st["method"] = method
    st["pairing_code"] = get_pairing_code(name) if method == "pairing" else None
    return st


def get_pairing_code(name: str) -> str | None:
    """读 check.js 落盘的配对码文件；无文件或内容非法返回 None。"""
    p = pairing_path_for(name)
    try:
        code = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return code or None


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
    pairing = pairing_path_for(name)
    if pairing.is_file():
        try:
            pairing.unlink()
            removed.append(pairing.name)
        except OSError:
            pass
    _sessions.pop(name, None)
    return {"ok": True, "name": name, "removed": removed}
