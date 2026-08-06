# -*- coding: utf-8 -*-
"""FetchFbPost 原子：匿名抓取 FB 群帖 permalink 并提取联系方式。

实测（docs/channel-research/facebook-groups.md §9）：群帖 permalink
匿名可读（登录墙只是遮罩，og:description + DOM 正文完整）；纯 HTTP GET
被 TLS 指纹拦截（400），必须经浏览器渲染 —— 故本原子复用 ctx.page
（浏览器会话由控制层装配，原子不管生命周期）。

契约：
    params = {
        "url":         str            必填，帖子 permalink
                                      （/groups/{gid}/posts/{pid}/）
        "timeout_ms":  int            可选，导航超时（缺省 60000）
        "render_wait": [float,float]  可选，渲染等待区间秒（缺省 2~4）
        "scroll":      bool           可选，渲染后滚一屏触发评论懒加载
                                      （缺省 True；评论留号是重要增量，
                                      真机实测评论是否渲染有随机性）
    }

返回：
    OK        data = {"url","final_url","title","og_description","text",
                      "phones","wa_group_invites","wechat_ids","tg_handles",
                      "has_contact"}
    EMPTY     帖子已删除/无权限（内容缺失文案），或页面无有效内容
    BLOCKED   匿名硬拦截（302 登录墙/频率限制页）
    NET_ERROR 导航超时/网络层错误
    FATAL     无活动页面/浏览器死亡
    SKIPPED   被停止信号中断
"""

from __future__ import annotations

import random

from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult
from fetcher.sites.facebook.features import (
    CONTENT_UNAVAILABLE_KEYWORDS,
    page_block_reason,
)
from fetcher.sites.facebook.post import parse_post

# 提取 og:description / og:title（免额外请求，meta 在首屏 HTML 里）
_JS_OG = """() => {
  const out = {description: '', title: ''};
  for (const m of document.getElementsByTagName('meta')) {
    const p = m.getAttribute('property');
    if (p === 'og:description') out.description = m.getAttribute('content') || '';
    if (p === 'og:title') out.title = m.getAttribute('content') || '';
  }
  return out;
}"""

_JS_BODY_TEXT = "() => document.body ? document.body.innerText : ''"

# 滚到页面底部触发评论懒加载
_JS_SCROLL_DOWN = "() => window.scrollTo(0, document.body.scrollHeight)"


class FetchFbPost:
    """抓取 FB 群帖（匿名）并分桶提取联系方式。"""

    name = "fetch_fb_post"
    title = "抓取FB群帖"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.stopped():
            return ActionResult.skipped("被停止信号中断")
        url = str((params or {}).get("url") or "").strip()
        if not url:
            return ActionResult.fatal("缺少必填参数 url（帖子 permalink）")
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")

        timeout = int(params.get("timeout_ms", 60000))
        wait_lo, wait_hi = params.get("render_wait", (2.0, 4.0))
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if ctx.wait(random.uniform(wait_lo, wait_hi)):
                return ActionResult.skipped("被停止信号中断")

            # 匿名硬拦截（302 登录墙 / 频率限制页）→ BLOCKED，交策略层处置
            reason = page_block_reason(page)
            if reason:
                return ActionResult.blocked(reason)

            # 滚一屏触发评论懒加载（评论留号是重要增量；实测无头会话里
            # 评论渲染有随机性，滚动后再等一拍提高命中率）
            if params.get("scroll", True):
                try:
                    page.evaluate(_JS_SCROLL_DOWN)
                except Exception:  # noqa: BLE001
                    pass  # 滚动失败不阻断，og/正文照提
                if ctx.wait(random.uniform(1.5, 2.5)):
                    return ActionResult.skipped("被停止信号中断")

            og = page.evaluate(_JS_OG) or {}
            text = page.evaluate(_JS_BODY_TEXT) or ""
            # 帖子删除/无权限是业务态 EMPTY（不是风控，换 IP 无意义）
            for kw in CONTENT_UNAVAILABLE_KEYWORDS:
                if kw in text:
                    return ActionResult.empty(f"帖子内容不可用（{kw}）")

            info = parse_post(og.get("description", ""), text)
            has_contact = bool(info["phones"] or info["wa_group_invites"]
                               or info["wechat_ids"] or info["tg_handles"])
            n_phones = len(info["phones"])
            detail = (f"提取 {n_phones} 个号码"
                      f"（自声明WA {sum(1 for p in info['phones'] if p['bucket'] == 'declared_wa')}）"
                      if n_phones else "未提取到号码")
            return ActionResult.success(detail, **{
                "url": url,
                "final_url": page.url,
                "title": og.get("title", ""),
                "og_description": og.get("description", ""),
                "text": text,
                **info,
                "has_contact": has_contact,
            })
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(f"浏览器死亡: {reason}")
            if kind == "net_error":
                return ActionResult.net_error(f"网络层错误: {reason}")
            return ActionResult.net_error(f"导航超时/卡顿: {reason}")
