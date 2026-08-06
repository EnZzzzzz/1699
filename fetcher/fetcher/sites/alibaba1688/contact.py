# -*- coding: utf-8 -*-
"""1688 联系人任务（迁移 contact_fetcher.py 的 ContactTask 全部行为）。

任务内容：从 1688.db 原子认领 status='pending' 的店铺，进入其
「联系方式」页解析 联系人/性别/电话/手机/传真/地址。

结果处理（与旧版一致）：
    - 座机或手机至少有一个 → contacts 表，店铺标记 done
    - 都为空 → 仍入 contacts 表备查，店铺标记 no_contact
    - 失败 → 标记 failed（--retry-failed 可重置）
断点续爬：进度全在 shops.status，中断残留的 in_progress 启动时
自动重置回 pending。

与旧版的有意差异：抓取内不再就地自动过证（判断与行动分离）——
命中风控由探测器判场景、SolveSlider 策略统一处置，行为等价。
"""

from __future__ import annotations

import random
import re
import time

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome

# 穿透 shadow DOM 提取页面文本（1688 联系方式等内容挂在
# <buyer-workbench> 的 shadowRoot 里，document.body.innerText 可能取不到）
_EXTRACT_TEXT_JS = """() => {
    const parts = [];
    const walk = (node, depth) => {
        if (depth > 60 || parts.length > 20000) return;
        if (node.nodeType === Node.TEXT_NODE) {
            const t = node.textContent.trim();
            if (t) parts.push(t);
            return;
        }
        if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE'
            || node.tagName === 'NOSCRIPT') return;
        if (node.shadowRoot) walk(node.shadowRoot, depth + 1);
        for (const c of (node.children || [])) walk(c, depth + 1);
    };
    walk(document.body || document.documentElement, 0);
    return parts.join('\\n');
}"""


def parse_contact_text(text: str) -> dict:
    """从联系方式页 innerText 解析字段。页面格式稳定:

        电话：86-757-xxxx   （可能只有区号/暂无）
        手机：138xxxxxxxx  （或 暂无）
        传真：暂无
        地址：广东xxx
        张三女士/先生        （联系人，性别由后缀推断）
    """

    def grab(label: str) -> str | None:
        m = re.search(rf"{label}[：:]\s*([^\n]*)", text)
        if not m:
            return None
        v = m.group(1).strip()
        if not v or v == "暂无" or v == "86":
            return None
        return v

    # 联系人：地址行之后、以 先生/女士 结尾的独立行
    contact_person, gender = None, None
    m = re.search(r"地址[：:][^\n]*\n\s*([^\n]{1,20}?)(先生|女士)\s*\n", text)
    if m:
        contact_person = m.group(1).strip() or None
        gender = {"先生": "男", "女士": "女"}.get(m.group(2))

    return {
        "phone": grab("电话"),
        "mobile": grab("手机"),
        "fax": grab("传真"),
        "address": grab("地址"),
        "contact_person": contact_person,
        "gender": gender,
    }


# 联系方式页的结构化标志：字段标签（有效页面必然带这些 label，
# 即使值为「暂无」）；用于 validate 判空，比文本长度阈值可靠
_CONTACT_LABELS = ("电话", "手机", "地址")

# 1688 店铺域名后缀：共享库多站点并存时按它过滤认领，防抓到 madeinchina 店铺
_SHOP_DOMAIN_SUFFIX = ".1688.com"


class ContactTask(Task):
    """联系人抓取任务：认领先前由 shop/company 任务入库的 pending 店铺。"""

    name = "contact"
    unit = "样本"
    batch_unit = ""

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        if getattr(config, "retry_failed", False):
            n = db.reset_failed(_SHOP_DOMAIN_SUFFIX)
            print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")
        n = db.reset_in_progress(_SHOP_DOMAIN_SUFFIX)
        if n:
            print(f"[0] 已把 {n} 个中断残留的 in_progress 店铺重置回 pending")
        # 共享库多站点并存：只认领 1688 的店铺（按域名后缀过滤），
        # 不碰 madeinchina 等其他来源的 pending 店铺
        total_pending = db.count_pending(_SHOP_DOMAIN_SUFFIX)
        if total_pending == 0:
            print(f"[OK] 没有待抓取的店铺。统计: {db.stats()}")
            print("    先运行 shop / company 任务采集更多店铺")
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
        tmd = db.format_tmd_report()
        db.close()
        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, "
                f"失败 {failed}\n    数据库统计: {stats}\n{tmd}")

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
        # 只认领 1688 的 pending 店铺（共享库防抓到 madeinchina 店铺）
        shops = ctx.store.db.claim_pending_shops(1, _SHOP_DOMAIN_SUFFIX)
        if not shops:
            return None
        return shops[0]

    def label(self, item) -> str:
        return item["name"] or item["domain"]

    def cold_start(self, ctx, item) -> None:
        """新会话的首个店铺先逛店铺首页留真实浏览轨迹，再进联系方式页
        —— 新会话一上来就深链 contactinfo.htm 是明显的爬虫特征。"""
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
        url = f"https://{domain}/page/contactinfo.htm"
        referer = item["url"] or f"https://{domain}/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(2.0, 4.0))
            # 优先穿透 shadow DOM 提取（buyer-workbench），失败退回 innerText
            text = ""
            try:
                text = page.evaluate(_EXTRACT_TEXT_JS) or ""
            except Exception:  # noqa: BLE001
                pass
            if len(text.strip()) < 30:
                text = page.evaluate("() => document.body.innerText") or ""
            info = parse_contact_text(text)
            info["_raw"] = text[:500]
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
        """结构化判空：有效联系方式页必然带 电话/手机/地址 字段标签
        （即使值为「暂无」），或解析出了任一字段。都不满足说明页面
        不是预期的联系方式页（软拦截/跳转错页），按 EMPTY 进策略链。
        """
        data = result.data or {}
        if any(data.get(k) for k in ("phone", "mobile", "fax", "address",
                                     "contact_person")):
            return True
        raw = data.get("_raw") or ""
        return any(label in raw for label in _CONTACT_LABELS)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        db = ctx.store.db
        stats = self.wctx_stats(ctx)
        info = dict(result.data)
        raw = info.pop("_raw", None)
        src = info.pop("_source_url", None)
        db.save_contact(item["domain"], info, source_url=src, raw_text=raw)
        if not (info.get("phone") or info.get("mobile")):
            # 座机和手机都为空即视为无有效联系方式：仍入 contacts 表备查
            db.mark_shop_no_contact(item["domain"], bump_attempts=False)
            stats["empty"] += 1
            ctx.set_status(state="无有效电话，标记 no_contact")
        else:
            stats["ok"] += 1
            ctx.set_status(state=f"✓ {info['contact_person'] or '-'}"
                                 f"({info['gender'] or '-'}) "
                                 f"电话={info['phone'] or '-'} "
                                 f"手机={info['mobile'] or '-'}")
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
