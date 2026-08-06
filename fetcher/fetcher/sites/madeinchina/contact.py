# -*- coding: utf-8 -*-
"""中国制造网(cn.made-in-china.com) 联系方式采集任务。

任务内容：从 1688.db 原子认领 status='pending' 的店铺（domain 为
{showroom}.cn.made-in-china.com 展厅子域名），进入其
showroom/{showroom}-contact.html 联系方式页，解析手机号/电话/传真/地址。

实测（2026-08-05）：联系方式页 **免登录**，手机号完整写死在
`<meta name="Description">` 里（`中国制造网，{公司}，联系人：{姓}，
联系电话：{手机号}`）；正文另含街道级地址、部分供应商传真、联系人（脱敏
只给姓）。页面 GBK 编码，由 Playwright 渲染自动解码，提取侧不做手动解码。
实测 76 供应商 75（99%）meta 里有完整手机号。

结果处理（与 1688 contact 一致）：
    - 手机号/电话至少有一个 → contacts 表，店铺标记 done
    - 都为空 → 仍入 contacts 表备查，店铺标记 no_contact
    - 失败 → 标记 failed（--retry-failed 可重置）
断点续爬：进度全在 shops.status，中断残留的 in_progress 启动时自动重置回
pending。

反爬：vemic FCaptcha 拦截页 URL 不变，由探测器按正文关键词/内嵌 iframe
判定；命中走策略链（休息→换 IP），不做就地过证（判断与行动分离）。
"""

from __future__ import annotations

import random
import re
import time

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.madeinchina.features import SHOWROOM_DOMAIN_SUFFIX

# 联系方式页 URL 前缀（拼 {showroom}-contact.html）
CONTACT_URL_TPL = "https://cn.made-in-china.com/showroom/{showroom}-contact.html"


def showroom_sub(domain: str) -> str:
    """"dihewujin.cn.made-in-china.com" → "dihewujin"（取展厅子域名）。"""
    return domain.removesuffix(SHOWROOM_DOMAIN_SUFFIX)


def contact_url_for(domain: str) -> str:
    """展厅子域名 → 联系方式页 URL。"""
    return CONTACT_URL_TPL.format(showroom=showroom_sub(domain))


# 提取 meta description（GBK 已由浏览器渲染解码，content 是正确字符串）
_JS_META_DESCRIPTION = """() => {
  for (const m of document.querySelectorAll('meta[name]')) {
    if ((m.getAttribute('name') || '').toLowerCase() === 'description')
      return m.getAttribute('content') || '';
  }
  return '';
}"""

_JS_BODY_TEXT = "() => document.body ? document.body.innerText : ''"


def _grab(text: str, label: str) -> str | None:
    """从正文提取 `label：value` 行；值空/「暂无」→ None。"""
    m = re.search(rf"{label}[：:]\s*([^\n]*)", text)
    if not m:
        return None
    v = m.group(1).strip()
    if not v or v == "暂无":
        return None
    return v


def _grab_phone(text: str) -> str | None:
    """提取正文里的座机行（独立「电话：」标签）。

    页面正文的「联系电话」行实际是「查看电话号码」按钮占位（号码只写在
    meta description 里），`_grab(text, "电话")` 会误把「联系电话：查看
    电话号码」整段捕获。这里用负向断言排除「联系电话」，并要求值以数字
    开头，杜绝占位文本进 phone 字段。
    """
    m = re.search(r"(?<!联系)电话[：:]\s*([0-9][0-9\-\s]{4,})", text)
    if not m:
        return None
    v = m.group(1).strip()
    if not v or v == "暂无":
        return None
    return v


def _clean_digits(v: str) -> str:
    return re.sub(r"\D+", "", v or "")


def _grab_body_contact(text: str) -> tuple[str | None, str | None]:
    """从正文提取 {姓名}{先生|女士|小姐}（{职务}）。

    平台联系方式页正文给的是完整联系人（如「程金明先生 （销售总监）」），
    而 meta description 的 联系人 字段常只给姓（脱敏）。优先用正文全名，
    顺带从 先生/女士 推断性别。返回 (姓名, 性别)。
    """
    m = re.search(r"([一-龥]{1,4}?)(先生|女士|小姐)", text)
    if not m:
        return None, None
    name = m.group(1).strip()
    gender = {"先生": "男", "女士": "女", "小姐": "女"}.get(m.group(2))
    return (name or None), gender


def parse_contact_page(meta: str, text: str) -> dict:
    """从联系方式页 meta description + 正文解析字段（纯函数，便于单测）。

    meta 格式稳定：`中国制造网，{公司}，联系人：{姓}，联系电话：{手机号}`
    （联系电话是裸 11 位手机号或座机，与 1688 contact 口径一致存裸号）。
    """
    # 手机号：meta 优先，正文兜底
    mobile = None
    m = re.search(r"联系电话[：:]\s*([0-9][0-9\s\-]{5,})", meta)
    if not m:
        m = re.search(r"联系电话[：:]\s*([0-9][0-9\s\-]{5,})", text)
    if m:
        digits = _clean_digits(m.group(1))
        if 8 <= len(digits) <= 15:
            mobile = digits

    # 联系人：正文优先（全名「程金明先生」→ 程金明），meta 兜底（常只给姓，
    # 脱敏）；两者都有时取更长的（正文姓名 ≥ 2 字，meta 姓 ≤ 2 字）
    body_name, body_gender = _grab_body_contact(text)
    meta_name = None
    m = re.search(r"联系人[：:]\s*([^\s，,]+)", meta)
    if m:
        meta_name = m.group(1).strip() or None
    if body_name and meta_name:
        contact_person = max((body_name, meta_name), key=len)
    else:
        contact_person = body_name or meta_name
    if not contact_person:
        contact_person = _grab(text, "联系人")

    company = None
    m = re.search(r"中国制造网，(.+?)，联系人", meta)
    if m:
        company = m.group(1).strip() or None

    return {
        "phone": _grab_phone(text),          # 座机，正文有才解析
        "mobile": mobile,                    # 裸号（与 1688 一致，86 由 wa 链路补）
        "fax": _grab(text, "传真"),
        "address": _grab(text, "地址"),
        "contact_person": contact_person,
        "gender": body_gender,               # 正文「先生/女士」推断；meta 只给姓无法推断
        "_company": company,
    }


# 联系方式页的结构化标志：字段标签（有效页面必然带这些 label，即使值为
# 「暂无」）；用于 validate 判空，比文本长度阈值可靠
_CONTACT_LABELS = ("地址", "联系人", "联系电话")


class MadeInChinaContactTask(Task):
    """中国制造网联系人任务：认领先前由 shop 任务入库的 pending 店铺。"""

    name = "contact"
    unit = "样本"
    batch_unit = ""

    # 实测慢速 + 带验证 cookie 的会话 80 页无拦截；预算保守取 80 [CAL]
    ip_request_budget = 80

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        if getattr(config, "retry_failed", False):
            n = db.reset_failed(SHOWROOM_DOMAIN_SUFFIX)
            print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")
        n = db.reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)
        if n:
            print(f"[0] 已把 {n} 个中断残留的 in_progress 店铺重置回 pending")
        # 共享库多站点并存：只认领 madeinchina 的店铺（按域名后缀过滤），
        # 不碰 1688 等其他来源的 pending 店铺
        total_pending = db.count_pending(SHOWROOM_DOMAIN_SUFFIX)
        if total_pending == 0:
            st = db.stats()
            # 共享库全库 pending 可能属于其他站点（如 1688），与 madeinchina
            # 的判定范围不同；单独标注避免与「没有待抓取」相矛盾
            print(f"[OK] 没有待抓取的 madeinchina 店铺"
                  f"（全库 pending {st['pending']} 均属其他站点）")
            print("    先运行 shop 任务采集更多店铺")
            db.close()
            return False
        print(f"[1] 待抓取 {total_pending} 个，每个 worker 每批 "
              f"{config.batch_num} 个"
              f"（{'最多 ' + str(config.max_batches) + ' 批'
                 if config.max_batches else '不限批数，抓完 pending 为止'}），"
              f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
        db.close()
        return True

    def summary(self, all_stats: dict) -> str:
        from fetcher.db import ShopDB  # 延迟导入
        ok = sum(s.get("ok", 0) for s in all_stats.values())
        empty = sum(s.get("empty", 0) for s in all_stats.values())
        failed = sum(s.get("failed", 0) for s in all_stats.values())
        db = ShopDB()
        stats = db.stats()
        db.close()
        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, "
                f"失败 {failed}\n    数据库统计: {stats}")

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                f"采 {f.get('n', 0)}（✓{f.get('ok', 0)} ○{f.get('empty', 0)} "
                f"✗{f.get('failed', 0)}）| 本IP {f.get('ip_n', 0)}次 | "
                f"{f.get('shop', '-')} | {f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"ok": 0, "empty": 0, "failed": 0}

    def rest_counter(self, stats: dict) -> int:
        return sum(stats.values())

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        # 只认领 madeinchina 的 pending 店铺（共享库防抓到 1688 店铺）
        shops = ctx.store.db.claim_pending_shops(1, SHOWROOM_DOMAIN_SUFFIX)
        if not shops:
            return None
        return shops[0]

    def label(self, item) -> str:
        return item["name"] or item["domain"]

    def cold_start(self, ctx, item) -> None:
        """新会话的首个店铺先逛展厅首页留真实浏览轨迹，再进联系方式页
        —— 新会话一上来就深链 -contact.html 是明显的爬虫特征。"""
        if item is None:
            return
        try:
            ctx.page.goto(f"https://{item['domain']}/",
                          wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(2.0, 5.0))
        except Exception:  # noqa: BLE001
            pass  # 首页打不开不阻断，照常走抓取流程

    def fetch(self, ctx, item) -> ActionResult:
        """进入店铺「联系方式」页并解析字段。"""
        page = ctx.page
        domain = item["domain"]
        url = contact_url_for(domain)
        referer = item["url"] or f"https://{domain}/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(2.0, 4.0))
            # 404 是「HTTP 200 + 重定向到 errorDocs/404.html」（实测非 404
            # 状态码），按最终 URL 判定：联系方式页不存在 = 死店/无联系方式
            # 页，是正常业务态不是风控，标记 dead 走 no_contact（不入库、不
            # 标 failed，避免 --retry-failed 白重试）
            if "errorDocs/404" in (page.url or ""):
                return ActionResult(Outcome.OK, "联系方式页不存在(404)",
                                    {"dead": True})
            meta = page.evaluate(_JS_META_DESCRIPTION) or ""
            text = page.evaluate(_JS_BODY_TEXT) or ""
            info = parse_contact_page(meta, text)
            info["_raw"] = (meta + "\n" + text)[:500]
            info["_source_url"] = page.url
            return ActionResult(Outcome.OK, "已解析联系方式页", info)
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(reason)
            if kind == "net_error":
                return ActionResult.net_error(reason)
            return ActionResult.blocked(f"页面加载失败（疑似风控拦截）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """结构化判空：有效联系方式页必带 地址/联系人/联系电话 标签或解析出
        任一字段（手机号写在 meta 里，正文可能是简短公司简介）。dead（404
        死店）是合法业务态，直接放行。"""
        data = result.data or {}
        if data.get("dead"):
            return True
        if any(data.get(k) for k in ("phone", "mobile", "fax", "address",
                                     "contact_person", "_company")):
            return True
        raw = data.get("_raw") or ""
        return any(label in raw for label in _CONTACT_LABELS)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        db = ctx.store.db
        stats = self.wctx_stats(ctx)
        if result.data.get("dead"):
            # 404 死店：联系方式页不存在，标 no_contact（不入 contacts 表，
            # 无任何可解析数据），不计 failed
            db.mark_shop_no_contact(item["domain"], bump_attempts=False)
            stats["empty"] += 1
            n_local = sum(stats.values())
            ctx.set_status(state="■ 联系方式页 404，标记 no_contact",
                           n=n_local, ok=stats["ok"], empty=stats["empty"],
                           failed=stats["failed"])
            return 1
        info = dict(result.data)
        raw = info.pop("_raw", None)
        src = info.pop("_source_url", None)
        db.save_contact(item["domain"], info, source_url=src, raw_text=raw)
        # 明文打印本店结果（店名 | 公司 | 联系人 | 手机 | 座机），方便实时
        # 确认是否捞到——状态行一刷新就被覆盖，打印落滚动日志
        shop_name = item["name"] if item["name"] else item["domain"]
        if not (info.get("phone") or info.get("mobile")):
            # 电话和手机都为空即视为无有效联系方式：仍入 contacts 表备查
            db.mark_shop_no_contact(item["domain"], bump_attempts=False)
            stats["empty"] += 1
            ctx.set_status(state="无有效电话，标记 no_contact")
            print(f"  ○ {shop_name} | {info.get('_company') or '-'} | "
                  f"{info.get('contact_person') or '-'} | 无电话",
                  flush=True)
        else:
            stats["ok"] += 1
            ctx.set_status(state=f"✓ {info['contact_person'] or '-'} "
                                 f"手机={info['mobile'] or '-'}")
            print(f"  ✓ {shop_name} | {info.get('_company') or '-'} | "
                  f"{info.get('contact_person') or '-'} | "
                  f"手机={info.get('mobile') or '-'} | "
                  f"座机={info.get('phone') or '-'}", flush=True)
        n_local = sum(stats.values())
        ctx.set_status(n=n_local, ok=stats["ok"], empty=stats["empty"],
                       failed=stats["failed"])
        return 1

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        ctx.store.db.mark_shop_failed(item["domain"])
        stats = self.wctx_stats(ctx)
        stats["failed"] += 1
        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
        return "标记 failed 跳过"

    def on_abort(self, ctx, item) -> str:
        return (f"店铺 {item['domain']} 留在 in_progress，"
                f"下次运行自动放回 pending")

    def giveup_cost(self, item) -> int:
        # 本店处理完毕（含标记 failed），计入批次配额
        return 1

    def empty_message(self) -> str:
        return "没有待抓取的店铺了"

    # ---- 内部 ----

    @staticmethod
    def wctx_stats(ctx) -> dict:
        return ctx.state["task"]["stats"]
