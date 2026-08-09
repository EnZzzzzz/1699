# -*- coding: utf-8 -*-
"""FetchDdgSerp 原子：DDG html 端点裸抓 FB 群帖 SERP + parse/classify 纯函数。

背景（docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md §8.1）：DDG
html 端点 GET + 浏览器 UA + gzip 可裸抓、无验证码；Bing 恒 challenge 不可用。
限流形态为约 2 连查后第 3 次 HTTP 202（anomaly 页），恢复窗口约 4 分钟——
本原子据此强制查询间节奏 ≥ 60s、202 退避 uniform(180,240)s。spike 实测样本
存 docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html。

契约：
    params = {
        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
                             原子强制下限 MIN_SAMPLE_FLOOR=60，spike 依据见上）
        "sample_max": float 可选，查询间节奏上限秒
        "timeout":    int   可选，HTTP 超时（缺省 30）
    }

返回：
    OK        data = {"engine":"ddg","query","page","results":[{"url","title",
              "kind","group_id","group_url"}...]}——全部有机结果不过滤，非 FB 的
              kind/group_id/group_url 为 None，分流交给上层任务（SPEC §5.2）
    EMPTY     200 但 0 条有机结果
    BLOCKED   HTTP 202（anomaly 限流，先退避 uniform(180,240)）/ 403 / 429
    NET_ERROR 传输错误 / 5xx / 超时
    FATAL     参数校验失败（query 缺失/非 str、page < 1）
    SKIPPED   被停止信号中断（请求前检查或等待期间置位）

依赖说明：只用标准库 urllib（符合包分层不引重依赖的约束）。
"""

from __future__ import annotations

import gzip
import html as html_mod
import random
import re
import urllib.error
import urllib.parse
import urllib.request

from fetcher.core.types import ActionResult

DDG_HTML = "https://html.duckduckgo.com/html/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# DDG 突发限流 spike 实测（SPEC §8.1）：约 2 连查后第 3 次即 202（anomaly 页），
# 202 触发到恢复的窗口实测约 4 分钟。查询间节奏下限 60s（~1 查询/分钟，低于
# 2 连查即封的突发阈值，留安全余量）。
MIN_SAMPLE_FLOOR = 60.0
# 202（anomaly 限流）退避：uniform(180, 240) 覆盖实测 ~4 分钟封禁窗口。
BLOCK_BACKOFF_MIN = 180.0
BLOCK_BACKOFF_MAX = 240.0

# SERP 有机结果锚点（spike 样本核实）：<a rel="nofollow" class="result__a"
# href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">标题</a>
RESULT_A_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', re.S)
UDDG_RE = re.compile(r"[?&]uddg=([^&]+)")
TAG_RE = re.compile(r"<[^>]+>")

# FB 帖 permalink：groups/<群id>/posts|permalink/<帖id（数字）>
POST_RE = re.compile(r"facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)")
# FB 群主页：groups/<群id>
GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")


def _http_get(url: str, timeout: float = 30) -> tuple[int, str]:
    """裸 GET，返回 (status, html)。传输层异常（URLError/socket.timeout）
    原样上抛；HTTPError（403/429/5xx 等）返回 (code, "") 由原子映射。
    独立成模块级函数：单测 monkeypatch 即可覆盖全部 HTTP 路径。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN",
        "Accept-Encoding": "gzip",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                body = gzip.decompress(body)
            return resp.status, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 4xx/5xx 状态码 → (code, "") 由原子映射（对齐 _http_json 模式）；
        # 其余传输异常不在此 catch，原样上抛。
        return e.code, ""


def parse_serp_results(html: str) -> list[dict]:
    """抽全部有机结果锚点 → uddg 参数 URL 解码 → 标题净化（去标签 + HTML 实体）。

    返回 [{"url","title"}...]，不过滤（FB 判定在 classify_fb_url）；
    无锚点/坏 HTML → []。
    """
    results = []
    for href, title in RESULT_A_RE.findall(html):
        href = html_mod.unescape(href)          # &amp; → &
        m = UDDG_RE.search(href)
        if not m:
            continue                            # 非 redirect 形态，跳过
        url = urllib.parse.unquote(m.group(1))
        title = html_mod.unescape(TAG_RE.sub("", title)).strip()
        results.append({"url": url, "title": title})
    return results


def classify_fb_url(url: str) -> tuple[str, str, str] | None:
    """分类 FB 群帖 URL：(kind, group_id, group_url) | None。

    kind="post"（帖 permalink）→ group_url 为派生的群主页；
    kind="group"（群主页）→ group_url 归一化到
    https://www.facebook.com/groups/{gid}（去尾部斜杠/协议差异）；
    其余（FB 视频/用户主页/广告页/非 FB）→ None。
    """
    m = POST_RE.search(url)
    if m:
        gid = m.group(1)
        return "post", gid, f"https://www.facebook.com/groups/{gid}"
    m = GROUP_RE.search(url)
    if m:
        gid = m.group(1)
        return "group", gid, f"https://www.facebook.com/groups/{gid}"
    return None


class FetchDdgSerp:
    """DDG html 端点裸抓 FB 群帖 SERP（查询 → 解析 → 分类）。"""

    name = "fetch_ddg_serp"
    title = "DDG抓FB群帖SERP"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.stopped():
            return ActionResult.skipped("被停止信号中断")
        params = params or {}
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            return ActionResult.fatal("缺少必填参数 query（查询词，str）")
        query = query.strip()
        raw_page = params.get("page")
        try:
            page = int(raw_page) if raw_page is not None else 1
        except (TypeError, ValueError):
            return ActionResult.fatal(f"page 参数无效: {raw_page!r}")
        if page < 1:
            return ActionResult.fatal(f"page 必须 ≥ 1（收到 {page}）")
        raw_timeout = params.get("timeout")
        timeout = int(raw_timeout) if raw_timeout is not None else 30
        # 查询间节奏：task 从 ctx.config 透传 sample_min/max（缺省 13-20s），
        # 原子强制下限 MIN_SAMPLE_FLOOR；上限低于地板时同样抬到地板，避免
        # uniform(a>b) ValueError（对齐 §8.1 设计数字）。用显式 None 判断而非
        # `or` 缺省（or 会吞掉显式 0）：sample_min=0 由地板抬到 60、
        # sample_max=0 由 max(sample_max, sample_min) 抬到 60；timeout=0 原样
        # 传给 _http_get（合法显式值，不转缺省 30）。
        raw_min = params.get("sample_min")
        sample_min = (float(raw_min) if raw_min is not None
                      else MIN_SAMPLE_FLOOR)
        sample_min = max(sample_min, MIN_SAMPLE_FLOOR)
        raw_max = params.get("sample_max")
        sample_max = (float(raw_max) if raw_max is not None
                      else (sample_min + 20.0))
        sample_max = max(sample_max, sample_min)

        url = f"{DDG_HTML}?q={urllib.parse.quote(query)}&s={(page - 1) * 10}"
        ctx.log(f"    ...DDG 查询「{query}」第 {page} 页")
        try:
            status, html = _http_get(url, timeout=timeout)
        except (OSError, TimeoutError, ValueError) as e:
            return ActionResult.net_error(f"DDG 请求失败: {e}")

        # 202（anomaly 限流）：先退避覆盖实测 ~4 分钟封禁窗口，再返回 BLOCKED。
        if status == 202:
            if ctx.wait(random.uniform(BLOCK_BACKOFF_MIN, BLOCK_BACKOFF_MAX)):
                return ActionResult.skipped("202 退避等待被停止信号中断")
        # 请求后统一节奏等待（无论 outcome）。
        if ctx.wait(random.uniform(sample_min, sample_max)):
            return ActionResult.skipped("节奏等待被停止信号中断")

        if status in (202, 403, 429):
            return ActionResult.blocked(f"DDG 限流/拒绝（HTTP {status}）")
        if status != 200:
            return ActionResult.net_error(f"DDG 返回异常状态 HTTP {status}")

        results = []
        for r in parse_serp_results(html):
            cls = classify_fb_url(r["url"])
            if cls is None:
                results.append({**r, "kind": None,
                                "group_id": None, "group_url": None})
            else:
                kind, group_id, group_url = cls
                results.append({"url": r["url"], "title": r["title"],
                                "kind": kind, "group_id": group_id,
                                "group_url": group_url})
        if not results:
            return ActionResult.empty("DDG 返回 0 条有机结果")

        return ActionResult.success(
            f"DDG 抓到 {len(results)} 条结果",
            engine="ddg", query=query, page=page, results=results)
