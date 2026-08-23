# -*- coding: utf-8 -*-
"""采集脚本（FB 直搜 / X 直搜 / WA 查号）进程与额度管理。

- 进程探测唯一事实源是进程表（pgrep -f 特征匹配），脚本可能由平台外启动；
- 脚本只认启动参数，调参靠「保存参数 + 重启进程」生效（不改 scraper/ 脚本）；
- 额度/产量统计：state JSON 读日用量，fb_contacts 只读查今日采集/查号数。
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from app.db import _write, connect, migrate

# 项目根（platform/server/app/scripts.py 上溯 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# X 总预算行数上限：$30 / $0.00015 每行 ≈ 200000（与 scraper/x_keyword_search.py
# 的 total_budget_usd 换算口径一致，脚本侧写死值，这里只做展示对照）
X_TOTAL_ROWS_CAP = 200000

# 脚本规格表：pgrep 特征 / 日志路径 / 启动命令模板 / 可调参数（键、默认值、范围）
SPECS = {
    "fb": {
        "title": "FB 关键词直搜",
        "sig": "scraper/fb_keyword_search.py",
        "log": ".cache/fb_keyword_search.log",
        "cmd": ["python3", "scraper/fb_keyword_search.py",
                "--keywords-file", ".cache/fb_keywords_extra.txt",
                "--memo23-daily-results", "{memo23_daily_results}"],
        "params": {"memo23_daily_results": {"default": 10000, "min": 1, "max": 1000000}},
    },
    "x": {
        "title": "X 关键词直搜",
        "sig": "scraper/x_keyword_search.py",
        "log": ".cache/x_keyword_search.log",
        "cmd": ["python3", "scraper/x_keyword_search.py",
                "--keywords-file", ".cache/x_keywords_all.txt",
                "--per-round", "5", "--interval", "600", "--delay", "3",
                "--daily-results", "{daily_results}"],
        "params": {"daily_results": {"default": 80000, "min": 1, "max": 1000000}},
    },
    "wa": {
        "title": "WhatsApp 查号",
        "sig": "scraper/wa_check_apify.py",
        "log": ".cache/wa_check_apify.log",
        "cmd": ["bash", "-c",
                "while true; do python3 scraper/wa_check_apify.py"
                " --bucket declared_wa,cn_uncertain --min-batch {min_batch};"
                " sleep 600; done"],
        "params": {"min_batch": {"default": 100, "min": 1, "max": 1000000}},
    },
}

# state JSON 路径（无 state 文件的脚本为 None）
_STATE_FILES = {
    "fb": ".cache/fb_keyword_search_state.json",
    "x": ".cache/x_keyword_search_state.json",
    "wa": None,
}


def _bj_today() -> str:
    return time.strftime("%Y-%m-%d")


# ==================== 配置读写 ====================

def _default_params(name: str) -> dict:
    return {k: v["default"] for k, v in SPECS[name]["params"].items()}


def ensure_configs() -> None:
    """seed 默认配置（INSERT OR IGNORE，幂等）。表由 db.migrate() 建。"""
    with connect() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    if "script_configs" not in tables:
        migrate()  # 表尚不存在（costs.sync 未跑过）时补建，幂等
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for name in SPECS:
        _write(
            "INSERT OR IGNORE INTO script_configs (name, params, updated_at)"
            " VALUES (?, ?, ?)",
            (name, json.dumps(_default_params(name)), now))


def get_params(name: str) -> dict:
    """读配置并与默认值合并（缺键补默认、坏 JSON 回退默认，防御性）。"""
    params = _default_params(name)
    with connect() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "script_configs" not in tables:
            return params
        row = conn.execute(
            "SELECT params FROM script_configs WHERE name=?", (name,)).fetchone()
    if row:
        try:
            saved = json.loads(row["params"] or "{}")
        except (ValueError, TypeError):
            saved = {}
        for key in params:
            try:
                val = int(saved.get(key))
            except (TypeError, ValueError):
                continue
            if val > 0:
                params[key] = val
    return params


def validate_params(name: str, params: dict) -> dict:
    """白名单校验：只认 SPECS 声明的参数键，值为限定范围内的正整数。

    非法键/值抛 ValueError（路由层转 422）。
    """
    spec = SPECS[name]["params"]
    clean = {}
    for key, val in (params or {}).items():
        if key not in spec:
            raise ValueError(f"未知参数 {key!r}（支持: {sorted(spec)}）")
        try:
            iv = int(val)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 必须是整数")
        if not (spec[key]["min"] <= iv <= spec[key]["max"]):
            raise ValueError(
                f"参数 {key} 超出范围 {spec[key]['min']}~{spec[key]['max']}")
        clean[key] = iv
    return clean


def save_params(name: str, params: dict) -> dict:
    """校验后 upsert 配置表（仅落库，不隐式重启）。返回保存后的完整参数。"""
    clean = validate_params(name, params)
    merged = get_params(name)
    merged.update(clean)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(
        "INSERT INTO script_configs (name, params, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET params=excluded.params,"
        " updated_at=excluded.updated_at",
        (name, json.dumps(merged), now))
    return merged


# ==================== 进程管理 ====================

def _pgrep(sig: str) -> list[int]:
    """pgrep -f 特征匹配，返回 pid 列表（无命中返回空）。"""
    res = subprocess.run(["pgrep", "-f", sig], capture_output=True, text=True)
    return [int(x) for x in res.stdout.split() if x.strip().isdigit()]


def _ps_info(pid: int) -> dict:
    """ps 取单个进程的启动时间/运行时长/命令行（进程已退出返回 None）。"""
    res = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "etime=", "-o", "command="],
        capture_output=True, text=True)
    line = res.stdout.strip()
    if not line:
        return None
    # lstart 固定 5 段（如 Sun Aug 23 15:00:00 2026），其后是 etime 与 command
    parts = line.split(None, 6)
    if len(parts) < 7:
        return None
    return {
        "started_at": " ".join(parts[:5]),
        "uptime": parts[5],
        "command": parts[6],
    }


def _is_script_proc(name: str, cmd: str) -> bool:
    """判断命令行是否真是目标脚本进程（而非仅含特征串的无关进程，
    如 curl /api/scripts/wa/stop 的调用方 shell）。"""
    if f"python3 {SPECS[name]['sig']}" in cmd:
        return True
    # WA 的 bash 循环壳 / nohup 包装壳：bash 开头且含脚本路径
    if name == "wa" and cmd.startswith(("bash", "/bin/bash")) \
            and SPECS[name]["sig"] in cmd:
        return True
    return False


def _match_pids(name: str) -> list[int]:
    """pgrep 初筛 + 命令行二次确认，返回确认属于目标脚本的 pid。"""
    out = []
    for pid in _pgrep(SPECS[name]["sig"]):
        info = _ps_info(pid)
        if info and _is_script_proc(name, info["command"]):
            out.append(pid)
    return out


def status(name: str) -> dict:
    """运行状态：主进程 pid + 启动时间 + 运行时长。

    主进程选取：FB/X 取命令行含 `python3 scraper/` 的；WA 取 bash 循环壳
    （python 子进程是单次跑批，循环壳才代表脚本在跑）。
    """
    pids = _match_pids(name)
    main = None
    for pid in pids:
        info = _ps_info(pid)
        if not info:
            continue
        cmd = info["command"]
        if name == "wa":
            if cmd.startswith(("bash", "/bin/bash")):
                main = {"pid": pid, **info}
                break
        elif "python3 scraper/" in cmd:
            main = {"pid": pid, **info}
            break
    if main is None and pids:
        main = {"pid": pids[0], "started_at": None, "uptime": None,
                "command": ""}
    return {
        "running": main is not None,
        "pid": main["pid"] if main else None,
        "started_at": main["started_at"] if main else None,
        "uptime": main["uptime"] if main else None,
    }


def start(name: str, params: dict = None) -> dict:
    """按配置（可叠加临时参数）启动脚本，等 1.5s 确认存活。

    子进程 cwd=项目根，stdout/stderr 追加进日志文件，start_new_session
    脱离后端进程组（后端退出不带走采集脚本）。已在运行则直接报错。
    """
    if status(name)["running"]:
        raise RuntimeError(f"「{SPECS[name]['title']}」已在运行中")
    merged = get_params(name)
    if params:
        merged.update(validate_params(name, params))
    cmd = [part.format(**{k: str(v) for k, v in merged.items()})
           for part in SPECS[name]["cmd"]]
    log_path = PROJECT_ROOT / SPECS[name]["log"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(
        cmd, cwd=str(PROJECT_ROOT), stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True)
    time.sleep(1.5)
    if proc.poll() is not None or not status(name)["running"]:
        logf.close()
        raise RuntimeError(
            f"启动失败（进程已退出），请查看日志 {SPECS[name]['log']} 尾部")
    return {"pid": proc.pid, "cmd": cmd}


def stop(name: str) -> dict:
    """SIGTERM 全部命中进程 → 轮询 5s → SIGKILL 兜底（搬 stop.sh 模式）。

    WA 是 bash 循环 + python 子进程两层，特征会同时命中，全杀。
    命中的进程经 _match_pids 二次确认命令行，避免误杀仅含特征串的无关进程。
    """
    pids = _match_pids(name)
    if not pids:
        return {"stopped": 0}
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 5
    while time.time() < deadline:
        alive = [p for p in pids if _ps_info(p) is not None]
        if not alive:
            break
        time.sleep(0.5)
    killed = 0
    for pid in _match_pids(name):
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except ProcessLookupError:
            pass
    return {"stopped": len(pids), "force_killed": killed}


def restart(name: str, params: dict = None) -> dict:
    """先停后启（stop + start）。"""
    stop(name)
    return start(name, params)


# ==================== 额度与产量统计 ====================

def _load_state(name: str) -> dict:
    """读 state JSON：文件不存在/JSON 损坏一律返回空 dict 不炸接口。"""
    rel = _STATE_FILES.get(name)
    if not rel:
        return {}
    try:
        return json.loads((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fb_contacts_count(where: str, params: tuple = ()) -> int:
    """fb_contacts 只读计数（表不存在防御性返回 0）。"""
    with connect() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fb_contacts" not in tables:
            return 0
        return conn.execute(
            f"SELECT COUNT(*) FROM fb_contacts WHERE {where}", params
        ).fetchone()[0]


def stats(name: str) -> dict:
    """各脚本今日用量/产量（键缺失返回 None，由前端展示 —）。"""
    today = _bj_today()
    state = _load_state(name)
    daily = (state.get("daily") or {}).get(today) or {}
    if name == "fb":
        return {
            "memo23_used": daily.get("memo23_results"),
            "memo23_limit": get_params(name)["memo23_daily_results"],
            "serp_queries": daily.get("serp_queries"),
            "collected_today": _fb_contacts_count(
                "post_url LIKE '%facebook%' AND substr(first_seen_at,1,10)=?",
                (today,)),
        }
    if name == "x":
        return {
            "x_used": daily.get("x_results"),
            "x_limit": get_params(name)["daily_results"],
            "total_results": state.get("total_results"),
            "total_cap": X_TOTAL_ROWS_CAP,
            "collected_today": _fb_contacts_count(
                "(post_url LIKE '%x.com%' OR post_url LIKE '%twitter%')"
                " AND substr(first_seen_at,1,10)=?", (today,)),
        }
    # wa：无 state 文件，今日已查/待查积压直接查库
    # （待查口径 = wa_registered IS NULL，见 AGENTS.md §4）
    return {
        "checked_today": _fb_contacts_count(
            "substr(wa_checked_at,1,10)=?", (today,)),
        "backlog": _fb_contacts_count(
            "bucket IN ('declared_wa','cn_uncertain') AND wa_registered IS NULL"),
    }


def tail_log(name: str, offset: int) -> dict:
    """日志增量 tail。

    - offset=0：返回最后约 200 行；
    - 0<offset<size：seek(offset) 读新增；
    - offset==size：无新内容；
    - offset>size：日志被截断，回退读尾部 64KB。
    """
    log_path = PROJECT_ROOT / SPECS[name]["log"]
    try:
        size = log_path.stat().st_size
    except OSError:
        return {"content": "", "offset": 0, "missing": True}
    offset = max(0, int(offset))
    with open(log_path, "rb") as f:
        if offset == 0 or offset > size:
            # 首次加载 / 日志截断回退：读尾部 64KB
            start = max(0, size - 64 * 1024)
            f.seek(start)
            data = f.read()
            text = data.decode("utf-8", errors="replace")
            if offset == 0:
                # 只保留最后约 200 行
                lines = text.splitlines()
                text = "\n".join(lines[-200:])
        elif offset < size:
            f.seek(offset)
            data = f.read(256 * 1024)  # 单次增量上限 256KB
            text = data.decode("utf-8", errors="replace")
        else:
            text = ""
    return {"content": text, "offset": size}
