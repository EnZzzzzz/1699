# -*- coding: utf-8 -*-
"""fetcher CLI 命令文本 → 任务 type + params 的反向解析（POST /api/tasks/parse）。

容忍形式：
- python -m fetcher ... / python3 -m fetcher ... / 直接 fetcher ...
- while/for 循环包裹 + sleep N → repeat_interval=N（秒）

flag 映射与 runner.build_command 正好反向。
"""

import re
import shlex


class CommandParseError(ValueError):
    """命令无法识别 → API 层转 422。"""


# (站点, 子任务) → 平台任务类型
SITE_TASKS = {
    ("1688", "shop"): "1688_shop",
    ("1688", "contact"): "1688_contact",
    ("1688", "company"): "1688_company",
    ("yiwugo", "search"): "yiwugo_search",
}

# 开关 flag → (params 键, 置为的值)
_BOOL_FLAGS = {
    "--proxy": ("use_proxy", True),
    "--headed": ("headless", False),
    "--no-auto-solve": ("auto_solve", False),
    "--retry-failed": ("retry_failed", True),
}

# 取值 flag → (params 键, 类型转换)；含 argparse 缩写形式 --worker
_VALUE_FLAGS = {
    "-n": ("batch_num", int),
    "--num": ("batch_num", int),
    "--limit": ("limit", int),
    "--max-batches": ("max_batches", int),
    "--workers": ("workers", int),
    "--worker": ("workers", int),
    "--channels": ("channels", int),
    "--batch-rest": ("batch_rest", float),
    "--sample-min": ("sample_min", float),
    "--sample-max": ("sample_max", float),
    "--rest-every": ("rest_every", int),
    "--rest-min": ("rest_min", float),
    "--rest-max": ("rest_max", float),
    "--stagger-min": ("stagger_min", float),
    "--stagger-max": ("stagger_max", float),
    "--ip-retry": ("ip_retry", int),
    "--net-retry": ("net_retry", int),
    "--max-consecutive-fail": ("max_consecutive_fail", int),
    "--block-rest-min": ("block_rest_min", float),
    "--block-rest-max": ("block_rest_max", float),
}

# 解释器 / 模块调用前缀
_PREFIX_WORDS = {"python", "python3", "-m", "fetcher"}

# shell 循环 / 结构关键字（静默忽略，不进 warnings）
_LOOP_WORDS = {"while", "do", "done", "true", "for", "in", "then", "fi",
               "if", "until", "until", "esac", "case"}

_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


def parse_command(command: str) -> dict:
    """命令文本 → {"type": ..., "params": {...}, "warnings": [...]}。

    无法识别站点任务时抛 CommandParseError。
    """
    warnings: list[str] = []
    try:
        tokens = shlex.split(command or "")
    except ValueError as e:
        raise CommandParseError(f"命令切分失败: {e}")
    # shell 分号会黏在 token 尾部（如 "true;" "1800;"），统一剥掉
    tokens = [t.rstrip(";") for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise CommandParseError("空命令")

    params: dict = {}

    # ---- 循环识别：sleep N（配合 while/for 循环或直接出现）----
    cleaned: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "sleep" and i + 1 < len(tokens) and _NUM_RE.match(tokens[i + 1]):
            n = int(float(tokens[i + 1]))
            if n > 0:
                params["repeat_interval"] = n
                warnings.append(f"检测到循环包裹，已设为每 {n} 秒自动重启")
            i += 2
            continue
        cleaned.append(tok)
        i += 1

    # ---- 定位站点任务：1688 shop/contact/company、yiwugo search ----
    idx = None
    for j, tok in enumerate(cleaned):
        if tok in ("1688", "yiwugo"):
            idx = j
            break
    if idx is None:
        raise CommandParseError(
            "无法识别站点任务：未找到 1688 / yiwugo 子命令；"
            "支持 1688 shop|contact|company、yiwugo search")
    if idx + 1 >= len(cleaned):
        raise CommandParseError(f"站点 {cleaned[idx]!r} 后缺少任务名")
    site, task = cleaned[idx], cleaned[idx + 1]
    task_type = SITE_TASKS.get((site, task))
    if not task_type:
        raise CommandParseError(
            f"无法识别的任务 {site} {task!r}；"
            "支持 1688 shop|contact|company、yiwugo search")

    # ---- 站点前的 token：解释器前缀 / 循环关键字跳过，其余进 warnings ----
    for tok in cleaned[:idx]:
        if tok in _PREFIX_WORDS or tok in _LOOP_WORDS:
            continue
        warnings.append(f"无法识别的 token: {tok}")

    # ---- flag 解析（与 build_command 反向）----
    rest = cleaned[idx + 2:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in _BOOL_FLAGS:
            key, val = _BOOL_FLAGS[tok]
            params[key] = val
            i += 1
        elif tok in _VALUE_FLAGS:
            key, conv = _VALUE_FLAGS[tok]
            if i + 1 >= len(rest):
                warnings.append(f"参数 {tok} 缺少取值，已忽略")
                i += 1
                continue
            raw = rest[i + 1]
            try:
                params[key] = conv(raw)
            except ValueError:
                warnings.append(f"参数 {tok} 取值 {raw!r} 无法解析，已忽略")
            i += 2
        elif tok.startswith("--") and "=" in tok:
            # --flag=value 形式
            flag, _, raw = tok.partition("=")
            if flag in _VALUE_FLAGS:
                key, conv = _VALUE_FLAGS[flag]
                try:
                    params[key] = conv(raw)
                except ValueError:
                    warnings.append(f"参数 {flag} 取值 {raw!r} 无法解析，已忽略")
            elif flag in _BOOL_FLAGS:
                key, val = _BOOL_FLAGS[flag]
                params[key] = val
            else:
                warnings.append(f"无法识别的 token: {tok}")
            i += 1
        elif tok in _LOOP_WORDS:
            i += 1
        else:
            warnings.append(f"无法识别的 token: {tok}")
            i += 1

    return {"type": task_type, "params": params, "warnings": warnings}
