# -*- coding: utf-8 -*-
"""FetchFbGroupPosts 原子：经第三方 API 采公开 FB 群帖子并提取联系方式。

背景（docs/channel-research/facebook-groups.md §11）：Bright Data / Apify
的群帖接口覆盖范围与自建匿名路线一致（仅公开群、无登录态），定位为
灾备/补充通道。2026-08-06 小额实测：两家返回同一批帖子，正文全文不
截断；BD 字段更全（群名/成员数/hashtags），Apify 同步调用更简单。

契约：
    params = {
        "url":      str   必填，公开群 URL（/groups/{id}）
        "provider": str   可选，"brightdata"（缺省）| "apify"
        "api_key":  str   可选；缺省按 provider 读环境变量
                          BRIGHTDATA_API_KEY / APIFY_TOKEN
        "limit":    int   可选，帖子数上限（缺省 10）
        "timeout":  int   可选，总超时秒（缺省 300；Apify 同步调用
                          单次请求即用此值，BD 为 trigger+轮询总预算）
    }

返回：
    OK        data = {"provider","group_url","post_count","posts",
                      "phones","wa_group_invites","wechat_ids","tg_handles",
                      "has_contact"}
              posts[i] = {"url","text","time","author","likes","comments",
                          "shares","group","provider", ＋parse_post 分桶}
    EMPTY     群无帖子 / 接口返回空
    BLOCKED   额度耗尽（402）或限流（429）——交策略层停用/降速
    NET_ERROR 传输错误 / 5xx / BD 快照失败 / 超时
    FATAL     缺参数、缺 API key、凭证无效（401/403）
    SKIPPED   被停止信号中断

依赖说明：只用标准库 urllib（符合包分层不引重依赖的约束）。
实测坑位（勿回归）：
    - BD 群帖发现只能走异步 /trigger；误用同步 /scrape 会报误导性的
      "Customer is not active"（账号本身没问题）。
    - BD 请求体是裸数组 [{"url":...}]，不是 {"input":[...]}。
"""

from __future__ import annotations

import json
import os
import urllib.request

from fetcher.core.types import ActionResult
from fetcher.sites.facebook.post import parse_post

BD_API = "https://api.brightdata.com/datasets/v3"
BD_DATASET_GROUP_POSTS = "gd_lz11l67o2cb3r0lkj3"   # FB posts by group URL

APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR_GROUP_SCRAPER = "apify~facebook-groups-scraper"

# provider -> (显示名, 环境变量名)
PROVIDERS = {
    "brightdata": ("Bright Data", "BRIGHTDATA_API_KEY"),
    "apify": ("Apify", "APIFY_TOKEN"),
}


class ProviderError(Exception):
    """第三方 API 返回的业务错误（status + 消息），由原子映射为 Outcome。"""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _http_json(method: str, url: str, *, headers: dict | None = None,
               payload=None, timeout: float = 30) -> tuple[int, object]:
    """发 JSON 请求，返回 (status, 解析后的 body)。传输层异常原样上抛。

    独立成模块级函数：单测 monkeypatch 此函数即可覆盖全部 HTTP 路径。
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body


# ---- 记录归一化（两家字段口径不同，统一成内部结构） ----

def norm_brightdata_post(rec: dict) -> dict:
    return {
        "url": rec.get("url") or "",
        "text": rec.get("content") or "",
        "time": rec.get("date_posted") or "",
        "author": rec.get("user_username_raw") or "",
        "likes": rec.get("likes") or 0,
        "comments": rec.get("num_comments") or 0,
        "shares": rec.get("num_shares") or 0,
        "group": rec.get("group_name") or "",
        "provider": "brightdata",
    }


def norm_apify_post(rec: dict) -> dict:
    user = rec.get("user") or {}
    return {
        "url": rec.get("url") or "",
        "text": rec.get("text") or "",
        "time": rec.get("time") or "",
        "author": user.get("name") or "",
        "likes": rec.get("likesCount") or 0,
        "comments": rec.get("commentsCount") or 0,
        "shares": rec.get("sharesCount") or 0,
        "group": rec.get("groupTitle") or "",
        "provider": "apify",
    }


# ---- provider 抓取（纯函数风格，HTTP 全走 _http_json 便于 mock） ----

def fetch_apify_posts(group_url: str, limit: int, api_key: str, *,
                      timeout: float, ctx) -> list[dict]:
    """Apify：同步一次调用直接拿数据。"""
    url = (f"{APIFY_API}/acts/{APIFY_ACTOR_GROUP_SCRAPER}"
           f"/run-sync-get-dataset-items?token={api_key}&timeout={int(timeout)}")
    payload = {"startUrls": [{"url": group_url}], "resultsLimit": limit}
    status, body = _http_json("POST", url, payload=payload, timeout=timeout + 30)
    if status // 100 != 2:
        raise ProviderError(status, _err_msg(body))
    return [norm_apify_post(r) for r in (body or [])]


def fetch_brightdata_posts(group_url: str, limit: int, api_key: str, *,
                           timeout: float, ctx) -> list[dict]:
    """Bright Data：trigger → 轮询 progress → 下载 snapshot（异步三段式）。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    status, body = _http_json(
        "POST",
        f"{BD_API}/trigger?dataset_id={BD_DATASET_GROUP_POSTS}"
        f"&include_errors=true",
        headers=headers,
        payload=[{"url": group_url, "num_of_posts": limit}],
        timeout=60)
    if status // 100 != 2:
        raise ProviderError(status, _err_msg(body))
    snapshot_id = (body or {}).get("snapshot_id")
    if not snapshot_id:
        raise ProviderError(status, f"trigger 未返回 snapshot_id: {body}")

    waited = 0.0
    interval = 10.0
    while True:
        if ctx.wait(interval):          # 可中断等待，兼作轮询节拍
            raise _Interrupted()
        waited += interval
        if waited > timeout:
            raise TimeoutError(f"BD 快照 {snapshot_id} 轮询超时（>{timeout:.0f}s）")
        status, body = _http_json("GET", f"{BD_API}/progress/{snapshot_id}",
                                  headers=headers, timeout=30)
        if status // 100 != 2:
            raise ProviderError(status, _err_msg(body))
        st = (body or {}).get("status")
        if st == "ready":
            break
        if st in ("failed", "dead"):
            raise ProviderError(200, f"BD 快照采集失败（status={st}）")

    status, body = _http_json("GET",
                              f"{BD_API}/snapshot/{snapshot_id}?format=json",
                              headers=headers, timeout=120)
    if status // 100 != 2:
        raise ProviderError(status, _err_msg(body))
    return [norm_brightdata_post(r) for r in (body or [])]


class _Interrupted(Exception):
    """轮询期间收到停止信号（内部控制流用）。"""


def _err_msg(body) -> str:
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message")
                   or body.get("errors") or body)[:200]
    return str(body)[:200]


class FetchFbGroupPosts:
    """第三方 API 采公开 FB 群帖子（Bright Data / Apify）并分桶提取联系方式。"""

    name = "fetch_fb_group_posts"
    title = "第三方采FB群帖"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.stopped():
            return ActionResult.skipped("被停止信号中断")
        params = params or {}
        url = str(params.get("url") or "").strip()
        if not url:
            return ActionResult.fatal("缺少必填参数 url（公开群 URL）")
        provider = str(params.get("provider") or "brightdata").lower()
        if provider not in PROVIDERS:
            return ActionResult.fatal(
                f"未知 provider「{provider}」（可选：{'/'.join(PROVIDERS)}）")
        label, env_key = PROVIDERS[provider]
        api_key = str(params.get("api_key") or os.environ.get(env_key) or "")
        if not api_key:
            return ActionResult.fatal(
                f"缺少 {label} API key（传 api_key 或设环境变量 {env_key}）")
        limit = int(params.get("limit") or 10)
        timeout = float(params.get("timeout") or 300)

        fetch = (fetch_brightdata_posts if provider == "brightdata"
                 else fetch_apify_posts)
        ctx.log(f"    ...{label} 采群帖 {url}（上限 {limit} 帖）")
        try:
            posts = fetch(url, limit, api_key, timeout=timeout, ctx=ctx)
        except _Interrupted:
            return ActionResult.skipped("被停止信号中断")
        except ProviderError as e:
            return self._map_provider_error(e, label)
        except (OSError, TimeoutError, ValueError) as e:
            return ActionResult.net_error(f"{label} 请求失败: {e}")

        if not posts:
            return ActionResult.empty("接口返回 0 帖（群为空或无权限）")

        # 逐帖提取联系方式（复用自建路线的 parse_post 分桶逻辑），
        # 跨帖按号码聚合去重（实测同一中介会连发多帖）
        seen: set[str] = set()
        phones: list[dict] = []
        invites: list[str] = []
        wechats: list[str] = []
        tgs: list[str] = []
        for p in posts:
            info = parse_post("", p["text"])
            p.update(info)
            p["has_contact"] = bool(info["phones"] or info["wa_group_invites"]
                                    or info["wechat_ids"] or info["tg_handles"])
            for ph in info["phones"]:
                if ph["number"] not in seen:
                    seen.add(ph["number"])
                    phones.append(ph)
            for src, agg in ((info["wa_group_invites"], invites),
                             (info["wechat_ids"], wechats),
                             (info["tg_handles"], tgs)):
                for x in src:
                    if x not in agg:
                        agg.append(x)

        return ActionResult.success(
            f"{label} 抓到 {len(posts)} 帖，提取 {len(phones)} 个唯一号码",
            provider=provider, group_url=url, post_count=len(posts),
            posts=posts, phones=phones, wa_group_invites=invites,
            wechat_ids=wechats, tg_handles=tgs, has_contact=bool(phones))

    @staticmethod
    def _map_provider_error(e: ProviderError, label: str) -> ActionResult:
        if e.status in (401, 403):
            return ActionResult.fatal(f"{label} 凭证无效/无权限: {e.message}")
        if e.status in (402, 429):
            return ActionResult.blocked(f"{label} 额度耗尽/限流: {e.message}")
        return ActionResult.net_error(f"{label} 接口错误: {e}")
