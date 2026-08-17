#!/usr/bin/env python3
# FB 关键词直搜采号常驻脚本：memo23 FB 原生搜索 + BD SERP 预览双源共用关键词库。
"""FB 关键词直搜采号（双源常驻，快脚本）。

合并两条已验证试点路线（/tmp/memo23_pilot.py、/tmp/serp_post_pilot.py）：

- memo23/facebook-search-scraper（Apify，FB 原生搜索 posts tab，免登录，
  $0.0019/结果）：每词 searchType=posts 正文 parse_post 挖中国号落
  fb_contacts（group_id=NULL）。用异步 run + 轮询（sync 端点实测会瞬断）。
  402/403 欠费按 wa_check_apify 口径记 quota_exhausted_at 并轮换账号
  （与 wa_check 共用账号额度，直接 import 它的 load_accounts/mark_exhausted）。
- Bright Data SERP 数据集 gd_mfz5x93lmsjjjylob（Google+Bing 各 1 页
  num=100）：查询词自动补 site:facebook.com 前缀，摘要预览 parse_post
  挖中国号落 fb_contacts（帖/主页链接都算，群链接派生 group_id）。

关键词轮转：词库一轮跑不完，--per-round 控制每轮词数，offset 存
.cache/fb_keyword_search_state.json（含按北京日期的当日用量记账），
下轮接着轮；失败的词本轮跳过，转一圈后自然重来。
预算刹车：当日 memo23 结果数 / SERP 查询数到顶即跳过该源（日志说明）。

用法：
  python3 scraper/fb_keyword_search.py --once --per-round 3   # 试跑一轮
  python3 scraper/fb_keyword_search.py --keywords-file /path/words.txt
  python3 scraper/fb_keyword_search.py                        # 常驻（默认 1h/轮）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fetcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetcher.atoms.facebook_discover import classify_fb_url  # noqa: E402
from fetcher.sites.facebook.post import parse_post  # noqa: E402
from fb_group_bd import is_cn_number  # noqa: E402
from wa_check_apify import load_accounts, mark_exhausted  # noqa: E402

STATE_PATH = REPO_ROOT / ".cache" / "fb_keyword_search_state.json"

# ---- memo23（Apify FB 原生搜索）----
MEMO23_ACTOR = "memo23~facebook-search-scraper"
APIFY_API = "https://api.apify.com/v2"
MEMO23_COST_PER_RESULT = 0.0019
RUN_POLL_SECS = 5
RUN_TIMEOUT_SECS = 300

# ---- Bright Data SERP ----
BD_API = "https://api.brightdata.com/datasets/v3"
BD_DATASET_SERP = "gd_mfz5x93lmsjjjylob"  # Google SERP（同数据集实测也收 Bing URL）
SCRAPE_TIMEOUT = 120

# FB 群 id 黑名单：groups/ 下的功能页不是群
NON_GROUP_GIDS = {"feed", "discover", "search", "join", "create", "recommended"}

# 内置关键词库（2026-08-18 全量实测策展版）：原 417 词经 WebBridge 真实
# 浏览器逐词验证（FB 搜索 posts 页，滚动加载后统计含中国号帖子数 C），
# 只保留 C>0 的 234 词；C=0 的 183 词（英文通用/小语种/无库存品类词）全部
# 清除。实测数据 docs/channel-research/kw-verify-2026-08-18/fb_*.jsonl + fb_retest.jsonl
KEYWORDS = [
    "whatsapp 货源", "whatsapp 厂家", "whatsapp 服装",
    "+86 whatsapp", "微信 货代", "whatsapp 义乌",
    "微信 采购 外贸", "微信 跨境电商", "微信 厂家直销",
    "whatsapp 供应商 批发", "微信 一手货源 代购", "whatsapp 批发 货源",
    "whatsapp 鞋", "whatsapp 箱包", "whatsapp 饰品",
    "whatsapp 美妆", "whatsapp 电子产品", "whatsapp 家具",
    "whatsapp 假发", "whatsapp 汽配", "微信 服装批发",
    "whatsapp 广州 批发", "whatsapp 工程机械", "whatsapp excavator",
    "whatsapp 机械", "whatsapp machinery", "whatsapp 重型机械",
    "whatsapp auto parts", "汽配 微信", "whatsapp 锂电池",
    "whatsapp 光伏", "whatsapp 储能", "whatsapp 新能源",
    "whatsapp 五金", "whatsapp 建材", "whatsapp 灯具",
    "whatsapp 手机配件", "whatsapp 手表", "whatsapp 包装",
    "whatsapp 纺织", "whatsapp 童装", "whatsapp 珠宝",
    "whatsapp 陶瓷", "whatsapp 卫浴", "whatsapp 厨具",
    "whatsapp 自行车", "whatsapp 电动车", "whatsapp 摩托车配件",
    "whatsapp 轮胎", "whatsapp 轴承", "whatsapp 泵阀",
    "whatsapp 模具", "whatsapp 货架", "whatsapp 礼品",
    "whatsapp 安防", "whatsapp 音响", "whatsapp 耳机",
    "whatsapp 充电宝", "whatsapp 数据线", "whatsapp 帽子",
    "whatsapp 围巾", "whatsapp 皮带", "whatsapp 袜子",
    "whatsapp shoes", "whatsapp bags", "whatsapp jewelry",
    "whatsapp furniture", "whatsapp toys", "whatsapp wigs",
    "whatsapp lighting", "whatsapp solar panel", "whatsapp battery",
    "whatsapp generator", "whatsapp welding machine", "whatsapp textile",
    "whatsapp 广州", "whatsapp 东莞", "whatsapp 泉州",
    "whatsapp 青岛", "whatsapp 中山", "whatsapp 汕头",
    "whatsapp 揭阳", "whatsapp 义乌 批发", "whatsapp 深圳 批发",
    "whatsapp 东莞 批发", "whatsapp 佛山 批发", "微信 五金",
    "微信 灯具", "微信 手机配件", "微信 手表",
    "微信 医疗器械", "微信 面料", "微信 卫浴",
    "微信 厨具", "微信 自行车", "微信 电动车",
    "微信 摩托车配件", "微信 轮胎", "微信 义乌 货源",
    "微信 深圳 货源", "微信 佛山 货源", "微信 泉州 货源",
    "微信 宁波 货源", "whatsapp 批发", "whatsapp 工厂",
    "whatsapp 供应商", "whatsapp 一手货源", "whatsapp 厂家直销",
    "whatsapp 一件代发", "whatsapp 外贸 出口", "whatsapp 跨境电商",
    "whatsapp OEM", "whatsapp ODM", "whatsapp supplier",
    "whatsapp manufacturer", "微信 批发", "微信 工厂",
    "微信 外贸 出口", "微信 OEM", "微信 ODM",
    "微信 亚马逊 FBA", "whatsapp 佛山 家具", "whatsapp 中山 灯具",
    "whatsapp 义乌 饰品", "whatsapp 东莞 电子", "whatsapp 泉州 鞋",
    "whatsapp 温州 鞋", "whatsapp 白沟 箱包", "whatsapp 汕头 玩具",
    "whatsapp 织里 童装", "whatsapp 台州 模具", "whatsapp 蓝牙耳机",
    "whatsapp 卷发棒", "whatsapp 电动牙刷", "whatsapp 加湿器",
    "whatsapp 监控摄像头", "whatsapp LED灯带", "whatsapp 太阳能路灯",
    "whatsapp 逆变器", "whatsapp 割草机", "whatsapp 叉车",
    "whatsapp 遥控车", "whatsapp 滑板车", "whatsapp 婴儿推车",
    "whatsapp 鱼缸", "whatsapp 行李箱", "微信 佛山 家具",
    "微信 广州 化妆品", "微信 义乌 玩具", "微信 东莞 电子",
    "微信 深圳 3C", "微信 泉州 鞋", "微信 温州 鞋",
    "微信 揭阳 五金", "whatsapp bluetooth earbuds", "whatsapp robot vacuum",
    "whatsapp CCTV camera", "whatsapp solar street light", "whatsapp inverter",
    "whatsapp water pump", "whatsapp forklift", "whatsapp 服装 尾货",
    "whatsapp 鞋 库存", "whatsapp 箱包 尾单", "whatsapp 饰品 尾货",
    "whatsapp 玩具 库存", "whatsapp 外贸 尾单", "whatsapp 尾货 批发",
    "whatsapp 品牌 尾货", "whatsapp 假睫毛", "whatsapp 母婴用品",
    "whatsapp 劳保用品", "whatsapp 仿真花", "whatsapp ropa china",
    "whatsapp zapatos china", "whatsapp juguetes china", "whatsapp fornecedor china",
    "whatsapp atacado china", "whatsapp поставщик китай", "whatsapp оптом китай",
    "whatsapp مورد الصين", "whatsapp alibaba", "whatsapp made in china",
    "whatsapp 速卖通", "whatsapp 敦煌网", "whatsapp canton fair",
    "whatsapp 广交会", "whatsapp proveedor mayorista china", "whatsapp proveedores chinos al por mayor",
    "whatsapp ملابس الصين", "whatsapp جملة الصين", "whatsapp товары из китая",
    "whatsapp китай оптом", "whatsapp bán buôn trung quốc", "whatsapp ซัพพลายเออร์จีน",
    "whatsapp ขายส่งจีน", "whatsapp juguetes al por mayor", "whatsapp bolsos china",
    "whatsapp ألعاب الصين", "whatsapp игрушки из китая", "whatsapp เสื้อผ้าขายส่ง",
    "whatsapp giày trung quốc", "whatsapp 双清包税到门", "whatsapp 集运",
    "whatsapp 整柜", "whatsapp 一手庄家", "whatsapp 海外仓",
    "whatsapp COD 货到付款", "whatsapp 询价 货代", "whatsapp 不甩柜",
    "whatsapp 台湾专线", "whatsapp 迪拜专线", "whatsapp 墨西哥专线",
    "whatsapp 智利专线", "whatsapp 迪拜 物流", "whatsapp 沙特 物流",
    "whatsapp 墨西哥 物流", "微信 专线 货代", "微信 敏感货",
    "微信 集运", "微信 整柜", "微信 拼箱",
    "微信 头程", "微信 一手庄家", "微信 海外仓",
    "whatsapp 复刻", "whatsapp 档口 货源", "whatsapp 市场 拿货",
    "寻找 货代", "求购 微信", "联系我 微信 货代",
    "微信同号", "VX 货代", "WS 货代",
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """账号级错误（BD 停用/欠费，或 Apify 全部耗尽），整轮中止信号。"""


# ---------------------------------------------------------------- 状态文件

def load_state() -> dict:
    """关键词轮转 offset + 按北京日期的当日用量（机器本地时区即北京）。"""
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
            st.setdefault("offset", 0)
            st.setdefault("daily", {})
            return st
        except Exception:
            pass
    return {"offset": 0, "daily": {}}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def today_usage(st: dict) -> dict:
    day = time.strftime("%Y-%m-%d")
    return st["daily"].setdefault(day, {"memo23_results": 0, "serp_queries": 0})


# ---------------------------------------------------------------- BD SERP

class BDClient:
    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"}

    def _poll_snapshot(self, snapshot_id: str, query: str) -> list[dict]:
        """同步 scrape 返回快照进行中时，轮询 Download Snapshot 取结果。

        2026-08-16 实测：BD 处理慢时 scrape 返回 {"snapshot_id": ...} 而非结果
        列表，此前被静默当 0 结果，BD 降级期约半数查询的数据就是这样丢的。
        进行中时下载端点返回 200 + {"status":"running"}（不是 202），实测快照
        就绪峰值约 3 分钟。
        """
        req = urllib.request.Request(
            f"{BD_API}/snapshot/{snapshot_id}?format=json", headers=self.headers)
        for i in range(24):  # 10s × 24 = 最多约 4 分钟
            time.sleep(10)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode() or "[]")
                if isinstance(data, list):
                    if i:
                        log(f"  快照轮询命中「{query}」（第{i + 1}次）")
                    return data
                # 200 + {"status":"running"}：仍在处理，继续轮询
            except urllib.error.HTTPError as e:
                if e.code == 202:
                    continue  # 仍在处理
                log(f"  快照轮询失败「{query}」: HTTP {e.code}")
                return []
            except Exception as e:  # noqa: BLE001
                log(f"  快照轮询异常「{query}」: {e}")
        log(f"  快照轮询超时「{query}」")
        return []

    def scrape_serp(self, query: str, engine: str = "google") -> list[dict]:
        """同步抓一页 SERP（1 次计费调用）。engine: google|bing。"""
        if engine == "bing":
            search_url = ("https://www.bing.com/search?q="
                          f"{urllib.parse.quote(query)}&count=50")
        else:
            search_url = (f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                          f"&num=100&hl=zh-CN")
        payload = [{"url": search_url, "keyword": query, "language": "zh-CN"}]
        req = urllib.request.Request(
            f"{BD_API}/scrape?dataset_id={BD_DATASET_SERP}&format=json",
            data=json.dumps(payload).encode(), method="POST",
            headers=self.headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as r:
                    body = json.loads(r.read().decode() or "[]")
                    if isinstance(body, list):
                        return body
                    if isinstance(body, dict) and body.get("snapshot_id"):
                        return self._poll_snapshot(body["snapshot_id"], query)
                    return []
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:200]
                log(f"  scrape 失败[{engine}]「{query}」: HTTP {e.code} {msg}")
                if e.code in (401, 402, 403) or "not active" in msg.lower() \
                        or "balance" in msg.lower():
                    raise AccountError(f"HTTP {e.code}: {msg}") from e
                return []
            except Exception as e:  # noqa: BLE001
                # 瞬时网络错误（SSL EOF/连接被断），退避后重试
                log(f"  scrape 异常[{engine}]「{query}」（第{attempt + 1}/3次）: {e}")
                time.sleep(min(2 ** attempt * 5, 20))
        return []


def serp_query(kw: str) -> str:
    """关键词 → SERP 查询：补 site: 前缀，联系方式词加引号提高命中。"""
    head, _, rest = kw.partition(" ")
    if head.lower() in ("whatsapp", "微信", "+86"):
        return f'site:facebook.com "{head}" {rest}'.strip()
    return f"site:facebook.com {kw}"


def harvest_serp(db, records: list[dict]) -> int:
    """SERP 标题/摘要挖中国号（帖/主页/群链接都算，群链接派生 group_id）。
    返回新增号码数。"""
    n_new = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get("error"):
            continue
        for item in rec.get("organic") or []:
            link = item.get("link") or ""
            if "facebook.com" not in link:
                continue
            text = f"{item.get('title') or ''}\n{item.get('description') or ''}"
            info = parse_post(text, text)
            phones = [p for p in info["phones"] if is_cn_number(p.get("number"))]
            if not phones:
                continue
            gid = None
            cls = classify_fb_url(link)
            if cls and cls[1] not in NON_GROUP_GIDS:
                gid = cls[1]
            n_new += db.save_fb_contacts(link, gid, phones)
    return n_new


# ---------------------------------------------------------------- memo23

def memo23_search(conn, accounts: list, kw: str, max_items: int) -> list[dict]:
    """异步 run + 轮询跑一个关键词，返回 dataset items。
    402/403 欠费记 quota_exhausted_at 并从 accounts 就地移除后换号重试；
    run FAILED / 瞬断重试 3 次，仍失败返回 []（留到下轮）。"""
    body = json.dumps({"searchType": "posts", "searchQueries": [kw],
                       "maxItems": max_items}).encode()
    for attempt in range(3):
        if not accounts:
            raise AccountError("全部 apify 账号额度耗尽")
        pid, name, token = accounts[0]
        try:
            req = urllib.request.Request(
                f"{APIFY_API}/acts/{MEMO23_ACTOR}/runs?token={token}",
                data=body, headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                run = json.loads(r.read().decode())["data"]
            run_id, ds_id = run["id"], run["defaultDatasetId"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (402, 403):  # 欠费/月硬顶：记耗尽换号
                mark_exhausted(conn, pid, name)
                accounts.pop(0)
                if accounts:
                    log(f"切换下一个 apify 账号：{accounts[0][1]}")
                continue
            log(f"  memo23 建 run 失败「{kw}」: HTTP {e.code} {detail}"
                f"（第{attempt + 1}/3次）")
            time.sleep(min(2 ** attempt * 5, 20))
            continue
        except Exception as e:  # noqa: BLE001
            log(f"  memo23 建 run 异常「{kw}」（第{attempt + 1}/3次）: {e}")
            time.sleep(min(2 ** attempt * 5, 20))
            continue

        deadline = time.time() + RUN_TIMEOUT_SECS
        status = "RUNNING"
        while time.time() < deadline:
            time.sleep(RUN_POLL_SECS)
            try:
                with urllib.request.urlopen(
                        f"{APIFY_API}/actor-runs/{run_id}?token={token}",
                        timeout=30) as r:
                    status = json.loads(r.read().decode())["data"]["status"]
            except Exception:  # noqa: BLE001
                continue  # 轮询瞬断不算失败，等下一拍
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        if status != "SUCCEEDED":
            log(f"  memo23 run「{kw}」状态 {status}（第{attempt + 1}/3次）")
            continue
        try:
            with urllib.request.urlopen(
                    f"{APIFY_API}/datasets/{ds_id}/items?token={token}",
                    timeout=60) as r:
                items = json.loads(r.read().decode())
            return items if isinstance(items, list) else []
        except Exception as e:  # noqa: BLE001
            log(f"  memo23 取结果异常「{kw}」（第{attempt + 1}/3次）: {e}")
    log(f"  memo23「{kw}」3 次均失败，留到下轮")
    return []


def harvest_memo23(db, items: list[dict]) -> int:
    """memo23 帖正文 parse_post 挖中国号落 fb_contacts（group_id=NULL）。
    返回新增号码数。"""
    n_new = 0
    seen_urls: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        text = it.get("text") or ""
        url = it.get("postUrl") or it.get("url") or ""
        if not text or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        info = parse_post(text, text)
        phones = [p for p in info["phones"] if is_cn_number(p.get("number"))]
        if phones:
            n_new += db.save_fb_contacts(url, None, phones,
                                         author=it.get("authorName"))
    return n_new


# ---------------------------------------------------------------- 主流程

def run_round(db, bd, accounts: list, keywords: list[str], args,
              st: dict) -> dict:
    """跑一轮：从 offset 取 per-round 个词，SERP+memo23 双源各挖一遍。"""
    usage = today_usage(st)
    n = len(keywords)
    batch = [keywords[(st["offset"] + i) % n] for i in range(args.per_round)]
    st["offset"] = (st["offset"] + args.per_round) % n
    save_state(st)
    stats = {"serp_queries": 0, "serp_new": 0,
             "memo23_results": 0, "memo23_new": 0}

    for kw in batch:
        # ---- SERP：Google+Bing 各 1 页 ----
        if usage["serp_queries"] >= args.serp_daily_queries:
            if stats["serp_queries"] or kw == batch[0]:
                log(f"  SERP 当日查询达顶 {args.serp_daily_queries}，跳过该源")
        else:
            q = serp_query(kw)
            for engine in ("google", "bing"):
                if usage["serp_queries"] >= args.serp_daily_queries:
                    break
                records = bd.scrape_serp(q, engine=engine)
                usage["serp_queries"] += 1
                stats["serp_queries"] += 1
                save_state(st)
                n_org = sum(len(r.get("organic") or []) for r in records
                            if isinstance(r, dict) and not r.get("error"))
                n_new = harvest_serp(db, records)
                stats["serp_new"] += n_new
                log(f"  [serp/{engine}]「{q}」: 结果 {n_org}，新号 +{n_new}")
                time.sleep(args.delay)

        # ---- memo23：FB 原生搜索 posts ----
        if accounts and usage["memo23_results"] < args.memo23_daily_results:
            items = memo23_search(conn=db.conn, accounts=accounts, kw=kw,
                                  max_items=args.memo23_max_items)
            usage["memo23_results"] += len(items)
            stats["memo23_results"] += len(items)
            save_state(st)
            n_new = harvest_memo23(db, items)
            stats["memo23_new"] += n_new
            log(f"  [memo23]「{kw}」: 帖 {len(items)}，新号 +{n_new}"
                f"（当日 {usage['memo23_results']}/{args.memo23_daily_results}）")
            time.sleep(args.delay)
        elif not accounts:
            log("  memo23 无可用 apify 账号，跳过该源")
        else:
            log(f"  memo23 当日结果达顶 {args.memo23_daily_results}，跳过该源")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="FB 关键词直搜采号（memo23+SERP 双源常驻）")
    ap.add_argument("--keywords-file",
                    help="追加关键词文件（一行一个，与内置词库合并去重）")
    ap.add_argument("--per-round", type=int, default=10, help="每轮关键词数")
    ap.add_argument("--interval", type=int, default=3600, help="两轮间隔秒数")
    ap.add_argument("--memo23-daily-results", type=int, default=2000,
                    help="memo23 当日结果数上限（缺省 2000 ≈ $3.8/天）")
    ap.add_argument("--serp-daily-queries", type=int, default=400,
                    help="SERP 当日查询数上限")
    ap.add_argument("--memo23-max-items", type=int, default=50,
                    help="memo23 每词 maxItems")
    ap.add_argument("--delay", type=float, default=5, help="查询间隔秒数")
    ap.add_argument("--once", action="store_true", help="跑一轮即退出")
    args = ap.parse_args()

    keywords = list(KEYWORDS)
    if args.keywords_file:
        for line in Path(args.keywords_file).read_text().splitlines():
            kw = line.strip()
            if kw and kw not in keywords:
                keywords.append(kw)
    log(f"关键词库 {len(keywords)} 个，每轮 {args.per_round} 个轮转")

    from fetcher.db import ShopDB  # 延迟导入（WAL + busy_timeout 30s）
    db = ShopDB()

    row = db.conn.execute(
        "SELECT config_json FROM providers WHERE kind='brightdata' AND enabled=1"
    ).fetchone()
    if not row:
        log("providers 表无 brightdata 凭证，退出")
        return 1
    bd = BDClient(json.loads(row[0])["api_key"])

    # apify 账号（与 wa_check 共用额度，402/403 自动轮换）；无账号则只跑 SERP
    try:
        accounts = load_accounts(db.conn)
        log(f"启用 apify 账号 {len(accounts)} 个："
            f"{'、'.join(a[1] for a in accounts)}")
    except SystemExit:
        log("无可用 apify 账号，memo23 源禁用，仅跑 SERP")
        accounts = []

    st = load_state()
    while True:
        try:
            stats = run_round(db, bd, accounts, keywords, args, st)
        except AccountError as e:
            log(f"账号不可用（{e}），10 分钟后重试")
            if args.once:
                return 1
            time.sleep(600)
            continue
        except Exception as e:  # noqa: BLE001
            log(f"本轮异常（{type(e).__name__}: {e}），下轮继续")
            if args.once:
                return 1
            time.sleep(args.interval)
            continue
        log(f"本轮：SERP 查询 {stats['serp_queries']} 次新号 +{stats['serp_new']}；"
            f"memo23 结果 {stats['memo23_results']} 条新号 +{stats['memo23_new']}"
            f"（memo23 花费≈${stats['memo23_results'] * MEMO23_COST_PER_RESULT:.3f}）")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
