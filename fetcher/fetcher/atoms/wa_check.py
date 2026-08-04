# -*- coding: utf-8 -*-
"""CheckWhatsApp 原子：输入手机号，返回是否注册过 WhatsApp。

实现方式：以子进程调用项目根 ``wa-check/`` 下的 Node/Baileys CLI
（``check.js``）。Baileys 以「已链接设备」身份走 WhatsApp 协议查询，
会话凭证保存在 ``wa-check/auth_info/``（首次需人工扫码登录，见下文）。

契约：
    params = {
        "numbers":      [str, ...]   必填，手机号（任意格式，自动规范化）
        "default_cc":   str          可选，国家码（如 "86"）；11 位且 1 开头
                                     的裸手机号自动补此前缀。缺省不补。
        "wa_check_dir": str | Path   可选，wa-check 目录；缺省读环境变量
                                     WA_CHECK_DIR，再缺省 <项目根>/wa-check
        "timeout":      float        可选，子进程总超时秒数（缺省 600）
    }

返回：
    OK        data["results"] = [{"number","registered","jid"|"error"}...]
    EMPTY     无有效号码
    SKIPPED   被停止信号中断
    NET_ERROR 连接 WhatsApp 失败 / 超时
    FATAL     node 缺失、wa-check 未安装、未登录（需人工扫码）等不可自愈错误

依赖说明：node 与 wa-check/node_modules 为外部重依赖，本模块只做
存在性检查，import 本身无任何重依赖（符合包的分层约束）。

首次登录（人工一次性操作）：
    cd wa-check && node check.js 8613800000000
    用手机 WhatsApp「已链接的设备」扫码（二维码同时存为 wa-check/qr.png）。
    建议使用备用小号：协议查询违反 WhatsApp ToS，有封号风险。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fetcher.core.context import PROJECT_ROOT
from fetcher.core.types import ActionResult

_DIGITS = re.compile(r"\D+")
_CN_MOBILE = re.compile(r"1\d{10}$")


def normalize_numbers(raw, default_cc: str = "") -> list[str]:
    """规范化号码为纯数字（E.164 不含 +），保留 8-15 位。

    default_cc 非空时，11 位且 1 开头的裸手机号自动补国家码
    （1688 联系人场景：mobile 字段通常是不带区号的大陆手机号）。
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        digits = _DIGITS.sub("", str(item or ""))
        if default_cc and _CN_MOBILE.fullmatch(digits):
            digits = default_cc + digits
        if 8 <= len(digits) <= 15 and digits not in seen:
            seen.add(digits)
            out.append(digits)
    return out


def resolve_wa_dir(params: dict) -> Path:
    """wa-check 目录：params > 环境变量 WA_CHECK_DIR > <项目根>/wa-check。"""
    p = params.get("wa_check_dir") or os.environ.get("WA_CHECK_DIR")
    return Path(p) if p else PROJECT_ROOT / "wa-check"


class CheckWhatsApp:
    """WhatsApp 查号原子：批量查询号码注册状态。"""

    name = "wa_check"
    title = "WhatsApp查号"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.stopped():
            return ActionResult.skipped("被停止信号中断")

        numbers = normalize_numbers(
            params.get("numbers"), str(params.get("default_cc") or ""))
        if not numbers:
            return ActionResult.empty("无有效号码（需带国家代码，或配合 default_cc）")

        wa_dir = resolve_wa_dir(params)
        cli = wa_dir / "check.js"
        if not cli.is_file():
            return ActionResult.fatal(
                f"wa-check CLI 不存在: {cli}（先部署 wa-check 或设置 wa_check_dir）")
        if not (wa_dir / "node_modules").is_dir():
            return ActionResult.fatal(
                f"wa-check 依赖未安装: {wa_dir}（cd wa-check && npm install）")
        node = shutil.which("node")
        if not node:
            return ActionResult.fatal("未找到 node 可执行文件（需 Node.js >= 18）")
        if not (wa_dir / "auth_info").is_dir():
            return ActionResult.fatal(
                "wa-check 未登录：cd wa-check && node check.js <任意号码>，"
                "手机扫码完成首次登录后重试")

        timeout = float(params.get("timeout", 600))
        ctx.log(f"    ...WhatsApp 查号 {len(numbers)} 个（{wa_dir.name}）")

        fd, list_path = tempfile.mkstemp(prefix="wa_nums_", suffix=".txt")
        results_path = tempfile.mktemp(prefix="wa_results_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(numbers))
            rc, out = self._run_node(
                [node, str(cli), list_path], ctx, timeout,
                cwd=wa_dir, results_path=results_path)
            if rc is None:
                return ActionResult.skipped("被停止信号中断（已终止子进程）")
            if rc == -1:
                return ActionResult.net_error(f"查号超时（>{timeout:.0f}s）")

            if rc != 0:
                if "已登出" in out:
                    return ActionResult.fatal(
                        "wa-check 会话已登出：删除 wa-check/auth_info 后重新扫码登录")
                if "重连失败" in out or "连接关闭" in out:
                    return ActionResult.net_error("无法连接 WhatsApp（多次重连失败）")
                return ActionResult.net_error(
                    f"check.js 退出码 {rc}: {out.strip().splitlines()[-1][:200] if out.strip() else '无输出'}")

            results = self._read_results(results_path)
            if results is None:
                return ActionResult.net_error("check.js 未产出结果文件")
            done = sum(1 for r in results if r.get("registered") is not None)
            hits = sum(1 for r in results if r.get("registered"))
            return ActionResult.success(
                f"查号完成 {done}/{len(results)}，已注册 {hits}",
                results=results, checked=done, registered=hits)
        finally:
            for p in (list_path, results_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # ---- 内部：子进程与结果读取（独立成方法便于单测替换） ----

    def _run_node(self, cmd, ctx, timeout: float, *,
                  cwd: Path, results_path: str) -> tuple[int | None, str]:
        """跑 node check.js；轮询停止信号。返回 (退出码, 合并输出)。

        退出码 None = 被中断已终止；-1 = 超时已终止。
        """
        env = dict(os.environ, WA_RESULTS=results_path)
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        waited = 0.0
        while proc.poll() is None:
            if waited >= timeout:
                proc.kill()
                proc.wait()
                return -1, ""
            if ctx.wait(1.0):          # 可中断等待，同时充当 1s 轮询节拍
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return None, ""
            waited += 1.0
        out = proc.stdout.read() if proc.stdout else ""
        return proc.returncode, out

    @staticmethod
    def _read_results(results_path: str):
        try:
            with open(results_path, encoding="utf-8") as f:
                return json.load(f).get("results", [])
        except (OSError, ValueError):
            return None
