# -*- coding: utf-8 -*-
"""
fetch_contact 原子：抓取联系方式。

抽取 server/app/workers/contact_fetch.py L224-357 的「单店铺抓取 + 入库 +
标记」语义，不含重试 / 换 IP / 熔断（那是引擎策略层的事，见
docs/flow-architecture.md §5.2）。outcome 映射：

    scrape_contact 返回 {"_net_error": ...}  → net_error（detail=原因）
    返回 None 或带 "_blocked"                → blocked（疑似风控）
    成功且座机/手机均空                       → empty（入库 + 标记 no_contact）
    成功且有联系方式                          → ok（data 带联系人/电话/手机）

pool_client.report 使用事件上报对齐 contact_fetch.py L232-234 / L239-241 /
L281-282；pool_client 或 channel 缺失（如单测）时跳过上报。
"""
from __future__ import annotations

from ...crawl import pages as pg
from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_BLOCKED, OUTCOME_EMPTY, OUTCOME_NET_ERROR, OUTCOME_OK,
)
from ..registry import register


def _report_usage(ctx: Context, result: str) -> None:
    """上报通道使用事件（contact_fetch.py 中 pool_client.report 的原样迁移）。"""
    pool_client = ctx.resources.get("pool_client")
    channel = ctx.resources.get("channel")
    if pool_client is None or channel is None:
        return
    pool_client.report(channel, result=result, task_type="contact_fetch",
                       exit_ip=ctx.resources.get("identity"))


def _field(shop, key, default=None):
    """兼容 dict 与 sqlite3.Row 的取值。"""
    try:
        v = shop[key]
    except (KeyError, IndexError):
        return default
    return v if v is not None else default


@register
class FetchContactAtom(Atom):
    name = "fetch_contact"
    title = "抓取联系方式"
    inputs = {"db": "ShopDB", "page": "Page",
              "vars.shops": "list[dict]（缺省取 [0]）"}
    outputs = {"data": "contact_person/phone/mobile（outcome=ok 时）"}
    param_spec = {
        "type": "object",
        "properties": {
            "shop": {
                "type": "object",
                "description": "显式指定店铺（缺省取 ctx.vars['shops'][0]，"
                               "便于单测与单点调试）",
            },
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        shop = params.get("shop")
        if shop is None:
            shops = ctx.vars.get("shops") or []
            shop = shops[0] if shops else None
        if not shop:
            return AtomResult(outcome=OUTCOME_EMPTY,
                              detail="没有待抓取的店铺（ctx.vars['shops'] 为空）")

        db = ctx.resources["db"]
        page = ctx.resources["page"]
        domain = _field(shop, "domain")
        referer = _field(shop, "url")
        label = f"{_field(shop, 'name') or domain}（{domain}）"

        # ---- 抓取 + 分类（contact_fetch.py L227-231，单次执行版）----
        info = pg.scrape_contact(page, domain, referer=referer)
        net_reason = info.pop("_net_error", None) if info else None
        block_reason = info.pop("_blocked", None) if info else None

        if info is not None and not net_reason and not block_reason:
            # ---- 成功：入库 + 标记（contact_fetch.py L232-236、L336-357）----
            _report_usage(ctx, "ok")
            raw = info.pop("_raw", None)
            src = info.pop("_source_url", None)
            db.save_contact(domain, info, source_url=src, raw_text=raw)
            if not (info.get("phone") or info.get("mobile")):
                db.mark_shop_no_contact(domain, bump_attempts=False)
                ctx.emit("info", f"{label} 无有效电话（座机/手机均空），"
                         "已记录条目并标记 no_contact",
                         {"domain": domain, "result": "no_contact"})
                return AtomResult(outcome=OUTCOME_EMPTY,
                                  detail=f"{label} 无有效电话，已标记 no_contact",
                                  data={"domain": domain})
            ctx.emit("success", f"{label} 抓取成功：联系人="
                     f"{info.get('contact_person')} 电话={info.get('phone')}"
                     f" 手机={info.get('mobile')}",
                     {"domain": domain, "result": "done",
                      "contact_person": info.get("contact_person"),
                      "phone": info.get("phone"), "mobile": info.get("mobile")})
            return AtomResult(
                outcome=OUTCOME_OK,
                detail=f"{label} 抓取成功",
                data={"domain": domain,
                      "contact_person": info.get("contact_person"),
                      "phone": info.get("phone"),
                      "mobile": info.get("mobile")})

        if net_reason:
            # ---- 网络/代理故障（contact_fetch.py L238-241）----
            _report_usage(ctx, "error")
            ctx.emit("warning", f"{label} 网络/代理故障（{net_reason}）",
                     {"domain": domain, "reason": net_reason})
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=net_reason,
                              data={"domain": domain})

        # ---- 疑似风控（contact_fetch.py L280-284：info 为 None 也落入该分支，
        #      原因即 L284 的 "页面加载失败（疑似风控拦截）"）----
        _report_usage(ctx, "blocked")
        reason = block_reason or "页面加载失败（疑似风控拦截）"
        ctx.emit("warning", f"{label} 疑似被风控（{reason}）",
                 {"domain": domain, "reason": reason})
        return AtomResult(outcome=OUTCOME_BLOCKED,
                          detail=reason,
                          data={"domain": domain})
