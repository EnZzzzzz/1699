# -*- coding: utf-8 -*-
"""采集脚本（FB 直搜 / X 直搜 / WA 查号 / 领英美国 HNW 直采）进程与额度管理。

- 进程探测唯一事实源是进程表（pgrep -f 特征匹配），脚本可能由平台外启动；
- 脚本只认启动参数，调参靠「保存参数 + 重启进程」生效（不改 scraper/ 脚本）；
- 额度/产量统计：state JSON 读日用量，fb_contacts 只读查今日采集/查号数；
- 选词启动（fb/x）：start 可带关键词子集，落盘 .cache/{name}_keywords_selected.txt
  并改写启动命令的词库文件参数（fb 用 --keywords-only-file 覆盖内置词库）；
  选择记录存 .cache/script_kw_selection.json，restart 沿用上次选词。
"""

import ast
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
    # 领英：无词库概念（同 wa）；target/max_budget 达顶脚本自行退出，
    # 其余参数（interval/limit/titles/locations）用脚本默认值不暴露
    "li": {
        "title": "领英美国 HNW 直采",
        "sig": "scraper/linkedin_us_search.py",
        "log": ".cache/linkedin_us_search.log",
        "cmd": ["python3", "scraper/linkedin_us_search.py",
                "--target", "{target}",
                "--max-budget", "{max_budget}"],
        "params": {"target": {"default": 500, "min": 1, "max": 1000000},
                   "max_budget": {"default": 80, "min": 1, "max": 100000}},
    },
    # 微信查号：runner 走本机 wxserver HTTP（127.0.0.1:19002，launchctl 服务，
    # 生命周期不归平台管）；跑一次直到未查清空自动退出，连续 5 error 熔断
    "wx": {
        "title": "微信查号",
        "sig": "platform/server/wx_lookup_runner.py",
        "log": ".cache/wx_lookup.log",
        "cmd": ["python3", "platform/server/wx_lookup_runner.py",
                "--interval", "{interval}"],
        "params": {"interval": {"default": 3, "min": 2, "max": 60}},
    },
}

# state JSON 路径（无 state 文件的脚本为 None）
_STATE_FILES = {
    "fb": ".cache/fb_keyword_search_state.json",
    "x": ".cache/x_keyword_search_state.json",
    "wa": None,
    "li": ".cache/linkedin_us_search_state.json",
    "wx": None,
}

# 默认词库文件（SPECS 启动命令里 --keywords-file 指向的文件）
_DEFAULT_KW_FILES = {
    "fb": ".cache/fb_keywords_extra.txt",
    "x": ".cache/x_keywords_all.txt",
}

# 内置词库提取源：脚本文件 + 列表字面量变量名（ast 静态解析，不 import 脚本）
_BUILTIN_SRC = {
    "fb": ("scraper/fb_keyword_search.py", "KEYWORDS"),
    "x": ("scraper/x_keyword_search.py", "X_KEYWORDS"),
}

# 选词记录：name → 选词文件相对路径（restart 沿用上次选词）
_SEL_STATE = ".cache/script_kw_selection.json"

# 选词启动时落盘的文件模板
_SEL_KW_FILE = ".cache/{}_keywords_selected.txt"


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


# ==================== 词库清单与选词启动（fb/x） ====================

def _read_words(rel: str) -> list[str]:
    """读词库文件（一行一词，去空行），文件不存在返回空列表。"""
    try:
        return [ln.strip() for ln in
                (PROJECT_ROOT / rel).read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        return []


def _builtin_keywords(name: str) -> list[str]:
    """ast 静态解析脚本源码里的内置词库列表字面量（不 import，避免重依赖）。

    解析失败/找不到返回空列表（防御性，不炸接口）。
    """
    src = _BUILTIN_SRC.get(name)
    if not src:
        return []
    path, var = src
    try:
        tree = ast.parse(
            (PROJECT_ROOT / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    for node in ast.walk(tree):
        # 同时匹配 `KEYWORDS = [...]` 与 `X_KEYWORDS: list[str] = [...]`
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (isinstance(target, ast.Name) and target.id == var
                and isinstance(value, (ast.List, ast.Tuple))):
            words = [el.value for el in value.elts
                     if isinstance(el, ast.Constant)
                     and isinstance(el.value, str)]
            if words:
                return words
    return []


def default_keywords(name: str) -> list[str]:
    """脚本默认生效词库（去重，保序）。

    - fb：内置 KEYWORDS + 追加文件（--keywords-file 合并语义）；
    - x：默认启动命令传了 --keywords-file（覆盖语义），词库=文件词，
      文件缺失/为空时回退内置 X_KEYWORDS；
    - wa：无词库概念，返回空。
    """
    if name == "fb":
        words = _builtin_keywords("fb")
        for w in _read_words(_DEFAULT_KW_FILES["fb"]):
            if w not in words:
                words.append(w)
        return words
    if name == "x":
        return _read_words(_DEFAULT_KW_FILES["x"]) or _builtin_keywords("x")
    return []


def _read_selection() -> dict:
    """读选词记录 JSON，损坏返回空 dict。"""
    try:
        return json.loads(
            (PROJECT_ROOT / _SEL_STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_selection(data: dict) -> None:
    path = PROJECT_ROOT / _SEL_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_keywords(name: str) -> dict:
    """选词面板数据：默认词库全量 + 退役标记 + 当前选词状态。"""
    retired = set((_load_state(name).get("kw_retired") or {}).keys())
    sel = _read_selection().get(name)
    sel_words = _read_words(sel) if sel else []
    return {
        "keywords": [{"word": w, "retired": w in retired}
                     for w in default_keywords(name)],
        "selection_active": bool(sel_words),
        "selected_count": len(sel_words) if sel_words else None,
    }


def _save_selection(name: str, keywords: list[str]) -> str:
    """选词落盘 .cache/{name}_keywords_selected.txt 并记录，返回文件相对路径。"""
    rel = _SEL_KW_FILE.format(name)
    path = PROJECT_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(keywords) + "\n", encoding="utf-8")
    data = _read_selection()
    data[name] = rel
    _write_selection(data)
    return rel


def _clear_selection(name: str) -> None:
    data = _read_selection()
    if name in data:
        del data[name]
        _write_selection(data)


def _swap_kw_arg(name: str, cmd: list[str], kw_rel: str) -> list[str]:
    """把启动命令里的 --keywords-file 参数值替换为指定词库文件。

    fb 选词需覆盖内置词库，flag 换成 --keywords-only-file；
    x 的 --keywords-file 本来就是覆盖语义，只换文件路径。
    """
    flag = "--keywords-only-file" if name == "fb" else "--keywords-file"
    if "--keywords-file" in cmd:
        i = cmd.index("--keywords-file")
        cmd[i] = flag
        cmd[i + 1] = kw_rel
    return cmd


def _resolve_kw_file(name: str, keywords: list[str] = None,
                     clear_keywords: bool = False) -> str:
    """决定本次启动使用的词库文件（仅 fb/x；其余返回 None）。

    - keywords 非空：落盘选词文件并记录；
    - clear_keywords：清除选词记录，用默认词库；
    - 否则沿用上次选词（文件还在的话），无记录用默认词库。
    """
    if name not in _DEFAULT_KW_FILES:
        return None
    if keywords:
        return _save_selection(name, keywords)
    if clear_keywords:
        _clear_selection(name)
        return _DEFAULT_KW_FILES[name]
    sel = _read_selection().get(name)
    if sel and (PROJECT_ROOT / sel).exists():
        return sel
    return _DEFAULT_KW_FILES[name]


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
        elif "python3 scraper/" in cmd or "python3 platform/" in cmd:
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


def _write_start_banner(name: str, logf, pid: int, params: dict,
                        cmd: list[str], kw_file: str = None) -> None:
    """启动分隔段：写进日志文件，区分历次运行并留档启动参数。"""
    lines = [
        "=" * 78,
        f"===== 启动「{SPECS[name]['title']}」"
        f" @ {time.strftime('%Y-%m-%d %H:%M:%S')} pid={pid}",
        f"===== 参数: {' '.join(f'{k}={v}' for k, v in params.items())}",
    ]
    if kw_file:
        kind = ("默认词库" if kw_file == _DEFAULT_KW_FILES.get(name)
                else "选词")
        lines.append(f"===== 词库: {kw_file}（{kind}，{len(_read_words(kw_file))} 个）")
    lines.append(f"===== 命令: {' '.join(cmd)}")
    lines.append("=" * 78)
    logf.write(("\n" + "\n".join(lines) + "\n").encode("utf-8"))


def start(name: str, params: dict = None, keywords: list = None,
          clear_keywords: bool = False) -> dict:
    """按配置（可叠加临时参数）启动脚本，等 1.5s 确认存活。

    子进程 cwd=项目根，stdout/stderr 追加进日志文件，start_new_session
    脱离后端进程组（后端退出不带走采集脚本）。已在运行则直接报错。

    fb/x 支持选词启动：keywords 为非空字符串列表时落盘选词文件并改写
    启动命令的词库参数；clear_keywords=True 清除选词记录回到默认词库；
    两者都不传则沿用上次选词（无记录用默认词库）。
    """
    if status(name)["running"]:
        raise RuntimeError(f"「{SPECS[name]['title']}」已在运行中")
    merged = get_params(name)
    if params:
        merged.update(validate_params(name, params))
    cmd = [part.format(**{k: str(v) for k, v in merged.items()})
           for part in SPECS[name]["cmd"]]
    if keywords is not None:
        keywords = [str(w).strip() for w in keywords if str(w).strip()]
        if not keywords:
            raise ValueError("选词列表不能为空（不选词请用 clear_keywords）")
    kw_file = _resolve_kw_file(name, keywords, clear_keywords)
    if kw_file:
        cmd = _swap_kw_arg(name, cmd, kw_file)
    log_path = PROJECT_ROOT / SPECS[name]["log"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(
        cmd, cwd=str(PROJECT_ROOT), stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True)
    _write_start_banner(name, logf, proc.pid, merged, cmd, kw_file)
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
    """先停后启（stop + start）。选词沿用上次记录（见 start）。"""
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


def _table_count(table: str, where: str, params: tuple = ()):
    """只读计数（表不存在防御性返回 None，由前端展示 —）。"""
    with connect() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in tables:
            return None
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()[0]


def _fb_contacts_count(where: str, params: tuple = ()) -> int:
    """fb_contacts 只读计数（表不存在防御性返回 0）。"""
    return _table_count("fb_contacts", where, params) or 0


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
    if name == "li":
        # 领英：进度/费用读 state JSON，产量读 us_leads/us_contacts
        # （两表由采集脚本自建，可能尚不存在，缺表返回 None 前端展示 —）
        params = get_params(name)
        return {
            "li_wa_registered": _table_count(
                "us_contacts", "wa_registered=1"),
            "li_target": params["target"],
            "li_cost": state.get("cost_usd"),
            "li_budget": params["max_budget"],
            "li_leads": _table_count("us_leads", "1=1"),
            "li_contacts": _table_count("us_contacts", "1=1"),
            "li_pending": _table_count(
                "us_contacts", "wa_registered IS NULL"),
            "li_combos": len(state.get("searched_combos") or []),
        }
    if name == "wx":
        # 微信查号：wx_* 列由 migrate 补建，缺列（migrate 未跑）返回 None 前端展示 —
        with connect() as conn:
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(fb_contacts)")}
        if "wx_registered" not in cols:
            return {"checked_today": None, "backlog": None}
        return {
            "checked_today": _fb_contacts_count(
                "substr(wx_checked_at,1,10)=?", (today,)),
            "backlog": _fb_contacts_count(
                "wx_registered IS NULL AND length(number) = 11"),
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
