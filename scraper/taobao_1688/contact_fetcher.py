#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 联系方式抓取（任务层 · 多 worker 并发由 common 网络层引擎驱动）

任务内容：从 .cache/1688.db 中原子认领 status='pending' 的店铺，进入其
「联系方式」页解析 联系人/性别(先生女士)/电话/手机/传真/地址。

本文件只含任务层逻辑：
    - parse_contact_text / scrape_contact  联系方式页解析（采什么）
    - ContactTask                          任务队列与结果入库
网络层（Cookie 按出口 IP 隔离、青果代理通道、浏览器生命周期、风控
状态机、批次休息、状态板）全部在 common.py 的 FetchTask / run_workers
引擎里，与 shop_crawler.py 共用同一套，禁止在这里另写网络逻辑。

结果处理:
    - 座机或手机至少有一个 → 写入 contacts 表，店铺标记 done
    - 座机和手机都为空（即使填了联系人/地址/传真）→ 同样写入 contacts
      表备查（含原始文本），店铺标记 no_contact，便于统计和后续复核
    - 抓取失败 → 店铺标记 failed（--retry-failed 可重置）

断点续爬:
    进度全部记录在 shops.status，随时 Ctrl+C 或重启脚本，
    下次运行自动把中断残留的 in_progress 重置回 pending 后继续。

用法:
    export CLOAKBROWSER_LICENSE_KEY=cb_xxx   # 或直接写进 .cache/config.json
    python3 contact_fetcher.py --proxy              # 5 通道 5 worker 并发
    python3 contact_fetcher.py --proxy -n 100       # 每个 worker 每批 100 个
    python3 contact_fetcher.py --proxy -n 50 --max-batches 4   # 最多采 4 批
    python3 contact_fetcher.py --proxy --headed     # 有头模式（首次过滑块）
    python3 contact_fetcher.py --retry-failed       # 先把 failed 重置回 pending
    python3 contact_fetcher.py --tmd-report         # 查看各 IP 的 tmd 触发率/安全线
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path

from common import (FetchTask, add_common_args, browser_alive,
                    is_fatal_browser_error, is_network_error,
                    page_block_reason, run_workers)
from database import ShopDB

# 滑块兜底：真人轨迹回放自动过证（轨迹库 util/tracks.json，录入/测试见
# util/slider_track.py）。导入失败时退化为纯检测（原有换 IP 重试行为）。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "util"))
try:
    from slider_track import solve_all_sliders
except Exception:
    solve_all_sliders = None


# 穿透 shadow DOM 提取页面文本（1688 联系方式等内容挂在 <buyer-workbench>
# 的 shadowRoot 里，document.body.innerText 可能取不到）
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


# ---------- 联系方式页解析（任务层：采什么） ----------

def parse_contact_text(text: str) -> dict:
    """
    从联系方式页 innerText 解析字段。页面格式稳定:

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


def scrape_contact(page, shop_domain: str, referer: str = None) -> dict | None:
    """进入店铺「联系方式」页并解析字段。

    返回值约定（引擎按优先级判断）：
        - 正常解析：dict，含联系方式字段 + _raw/_source_url/_blocked
        - 浏览器进程死亡/被服务端关闭（TargetClosed、崩溃等，非风控）：
          返回 {"_fatal": <原因>} 标记 dict，引擎直接重启浏览器重试
        - 网络/代理层错误（隧道断、连接重置等，与风控无关）：
          返回 {"_net_error": <原因>} 标记 dict，引擎换通道/退避重试
        - 其他异常（超时、解析失败等）：返回 None（按风控处理）
    """
    url = f"https://{shop_domain}/page/contactinfo.htm"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000,
                  referer=referer or f"https://{shop_domain}/")
        time.sleep(random.uniform(2.0, 4.0))
        # 滑块兜底：命中风控/待验证时先尝试自动过证。
        # 重试策略（solve_with_retry，max_attempts=5）：
        #   第 1 次回放不过 → 点击"验证失败"框体重置，换条轨迹原地再试；
        #   还不过 → 刷新页面重新等滑块、重新量距，再换轨迹试，
        #   如此"点击重试 → 刷新 → 再试"最多重复 5 次（含约 2 轮刷新）。
        # 过证后继续解析本页；过不了则照常走下面的 _blocked 检测，由引擎换 IP 重试
        if solve_all_sliders is not None and page_block_reason(page):
            try:
                if solve_all_sliders(page, max_attempts=5):
                    time.sleep(random.uniform(1.5, 2.5))  # 等真实内容渲染
            except Exception:
                pass  # 过证异常不阻断，交给 _blocked 判定兜底
        # 优先穿透 shadow DOM 提取（buyer-workbench），失败退回 innerText
        text = ""
        try:
            text = page.evaluate(_EXTRACT_TEXT_JS) or ""
        except Exception:
            pass
        if len(text.strip()) < 30:
            text = page.evaluate("() => document.body.innerText") or ""
        info = parse_contact_text(text)
        info["_raw"] = text[:500]
        info["_source_url"] = page.url
        # 风控拦截检测：命中时返回原因字符串，引擎据此换 IP 重试
        info["_blocked"] = page_block_reason(page)
        return info
    except Exception as e:
        reason = str(e).splitlines()[0][:200]
        # 1) 浏览器进程级致命错误（会话被服务端关闭、崩溃等），优先识别
        if is_fatal_browser_error(e):
            return {"_fatal": reason}
        # 2) 网络/代理层错误
        if is_network_error(e):
            return {"_net_error": reason}
        # 3) 其他异常（多为 goto 超时）：先鉴别浏览器是不是已经死了
        if not browser_alive(page):
            return {"_fatal": f"浏览器连接断开: {reason}"}
        return None


# ---------- 任务定义 ----------

class ContactTask(FetchTask):
    """联系人抓取任务：认领先前由 shop_crawler 入库的 pending 店铺。"""

    unit = "样本"
    batch_unit = ""

    # ---- main 阶段 ----

    def prepare(self, args) -> bool:
        db = ShopDB()
        if args.retry_failed:
            n = db.reset_failed()
            print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")
        # 上次中断残留的 in_progress 全部放回 pending
        n = db.reset_in_progress()
        if n:
            print(f"[0] 已把 {n} 个中断残留的 in_progress 店铺重置回 pending")

        total_pending = db.count_pending()
        if total_pending == 0:
            print(f"[OK] 没有待抓取的店铺。统计: {db.stats()}")
            print("    先运行 shop_crawler.py 采集更多店铺")
            db.close()
            return False
        print(f"[1] 待抓取 {total_pending} 个，每个 worker 每批 {args.num} 个"
              f"（{'最多 ' + str(args.max_batches) + ' 批' if args.max_batches else '不限批数，抓完 pending 为止'}），"
              f"批间强制休息 {args.batch_rest / 60:.0f} 分钟")
        db.close()
        return True

    def summary(self, all_stats: dict) -> str:
        ok = sum(s["ok"] for s in all_stats.values())
        empty = sum(s["empty"] for s in all_stats.values())
        failed = sum(s["failed"] for s in all_stats.values())
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

    def acquire(self, db, wctx: dict):
        shops = db.claim_pending_shops(1)
        if not shops:
            return None
        return shops[0]

    def label(self, item) -> str:
        return item["name"] or item["domain"]

    def cold_start(self, page, item, log=None) -> None:
        """新会话的首个店铺先逛店铺首页留真实浏览轨迹，再进联系方式页
        —— 新会话一上来就深链 contactinfo.htm 是明显的爬虫特征。"""
        try:
            page.goto(f"https://{item['domain']}/",
                      wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(2.0, 5.0))
        except Exception:
            pass  # 首页打不开不阻断，照常走抓取流程

    def scrape(self, page, item) -> dict | None:
        return scrape_contact(page, item["domain"], referer=item["url"])

    def on_success(self, db, item, info: dict, wctx: dict,
                   set_status, log) -> int:
        stats = wctx["stats"]
        raw = info.pop("_raw", None)
        src = info.pop("_source_url", None)
        db.save_contact(item["domain"], info, source_url=src, raw_text=raw)
        if not (info.get("phone") or info.get("mobile")):
            # 座机和手机都为空即视为无有效联系方式（只填联系人/地址/传真
            # 也不算）：仍入 contacts 表备查，店铺标记 no_contact
            db.mark_shop_no_contact(item["domain"], bump_attempts=False)
            stats["empty"] += 1
            set_status(state="无有效电话，标记 no_contact")
        else:
            stats["ok"] += 1
            set_status(state=f"✓ {info['contact_person'] or '-'}"
                             f"({info['gender'] or '-'}) "
                             f"电话={info['phone'] or '-'} "
                             f"手机={info['mobile'] or '-'}")
        n_local = sum(stats.values())
        set_status(n=n_local, ok=stats["ok"], empty=stats["empty"],
                   failed=stats["failed"])
        return 1

    def on_giveup(self, db, item, reason: str, kind: str, wctx: dict,
                  set_status, log) -> str:
        db.mark_shop_failed(item["domain"])
        stats = wctx["stats"]
        stats["failed"] += 1
        set_status(n=sum(stats.values()), failed=stats["failed"])
        return "标记 failed 跳过"

    def on_abort(self, item) -> str:
        return (f"店铺 {item['domain']} 留在 in_progress，"
                f"下次运行自动放回 pending")

    def empty_message(self) -> str:
        return "没有待抓取的店铺了"

    def giveup_cost(self, item) -> int:
        # 本店处理完毕（含标记 failed），计入批次配额
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="1688 店铺联系方式抓取（任务层；"
                    "多 worker 并发/风控状态机由 common 网络层引擎驱动）")
    ap.add_argument("-n", "--num", type=int, default=10,
                    help="每个 worker 每批抓取的店铺数量（默认 10）；"
                         "采满一批后各自强制休息再开下一批")
    ap.add_argument("--retry-failed", action="store_true",
                    help="先把 failed 店铺重置为 pending 再开始抓取")
    ap.add_argument("--tmd-report", action="store_true",
                    help="只打印各出口 IP 的 tmd（反爬验证）触发统计"
                         "（tmd率/触发间隔/安全线）后退出，不抓取")
    add_common_args(ap)
    args = ap.parse_args()

    if args.tmd_report:
        db = ShopDB()
        print(db.format_tmd_report())
        db.close()
        return 0

    task = ContactTask()
    if not task.prepare(args):
        return 0
    return run_workers(args, task)


if __name__ == "__main__":
    sys.exit(main())
