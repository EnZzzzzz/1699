#!/usr/bin/env python3
# FB 关键词直搜采号常驻脚本：memo23 FB 原生搜索 + BD SERP 预览双源共用关键词库。
"""FB 关键词直搜采号（双源常驻，「牧场」模型，2026-08-21 重写，与 X 同款策略）。

老版（纯轮转：每轮 per-round 词各扫一遍）已废弃——高频重扫同一批词，
返回的基本是同一批帖，预算花在重复结果上。新版与 X 脚本同策略：

  每个词到期（距上次采集 ≥ SCAN_INTERVAL 天，默认 3 天）就开一次采集会话：
  - SERP（Google+Bing 各 1 页）：搜索引擎结果无深挖空间，一次到位；
  - memo23 刺探最新 PROBE_ITEMS(50) 帖：挖到新号 → maxItems 按
    DIG_MULTIPLIER(4) 倍增深翻（50→200→400，封顶 DIG_MAX_ITEMS；memo23
    无分页游标，深一批 = 重跑一轮更大 maxItems，按交付结果计费，
    seen_urls 去重只处理新帖），直到某批新号 +0 / 帖空 / 单批到顶
    才换词（实测单词 FB 链接封顶 ~100-120，第 3 页起≈0——死词靠 +0 批
    提前止损，热词单词会话最多交付 50+200+400=650 条 ≈ $1.24）；
  - 整会话一个新号都没有 → 连击 +1；
  - 连续 RETIRE_STRIKES(3) 次会话无新号（≈9 天无产出）→ 判枯竭退役，
    记 state.kw_retired 永久移出轮转（词库文件不动，留 3 天间隔就是给
    词「长新帖」的时间）。
  运营方式：持续往词库加验证过的新词（AGENTS.md 换词流程），之后全自动。

数据源（双源共用词库，互不依赖、互为补充）：
- memo23/facebook-search-scraper（Apify，FB 原生搜索 posts tab，免登录，
  $0.0019/结果）：帖正文 parse_post 挖中国号落 fb_contacts（group_id=NULL）。
  用异步 run + 轮询（sync 端点实测会瞬断）。402/403 欠费按 wa_check_apify
  口径记 quota_exhausted_at 并轮换账号（与 wa_check 共用额度，直接 import
  它的 load_accounts/mark_exhausted）。
- Bright Data SERP 数据集 gd_mfz5x93lmsjjjylob（Google+Bing 各 1 页
  num=100）：查询词自动补 site:facebook.com 前缀，摘要预览 parse_post
  挖中国号落 fb_contacts（帖/主页链接都算，群链接派生 group_id）。

跨源去重：number 列有 UNIQUE 约束（save_fb_contacts 走 INSERT OR IGNORE），
但同号可能一边存 86 前缀形态、一边存裸 11 位，精确匹配挡不住，故落库前
先 SELECT 查重（后 11 位对齐，与 X 脚本同口径），命中即跳过——深挖的
「新号 +0 即收工」判据也依赖这个准确的新号计数。

成本量级：刺探 50 帖 ≈ $0.1/词/次；深挖顶格 50+100+150=300 结果 ≈ $0.57，
仅热词触发。预算刹车：当日 memo23 结果数 / SERP 查询数到顶即跳过该源
（按北京日期跨天自动清零）。

状态文件 .cache/fb_keyword_search_state.json（与 X 的 state 互相独立）：
  offset        轮转游标（取词起点，扫过的词 3 天内自然不再到期）
  daily         按北京日期的当日用量（memo23_results / serp_queries）
  kw_stats      每词 q/posts/new/first_at/last_q_at/last_new_at/zero_streak
                （zero_streak=连续无新号会话数，满 3 退役；kw_stats.py 报表用）
  kw_retired    已退役词 {词: {at, strikes, q}}；误判复活：删对应键即可
  ranch_v1      一次性迁移旗标：旧连击是高频轮转时代累计的，语义不同，
                首次加载清零 zero_streak

用法：
  python3 scraper/fb_keyword_search.py --once --per-round 3   # 试跑一轮
  python3 scraper/fb_keyword_search.py --keywords-file /path/words.txt
  python3 scraper/fb_keyword_search.py                        # 常驻（默认 1h/轮）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fetcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetcher.sites.facebook.discover import classify_fb_url  # noqa: E402
from fetcher.sites.facebook.post import parse_post  # noqa: E402
from fb_group_bd import is_cn_number  # noqa: E402
from wa_check_apify import load_accounts, mark_exhausted  # noqa: E402

STATE_PATH = REPO_ROOT / ".cache" / "fb_keyword_search_state.json"

# ---------------------------------------------------------------- 策略参数
SCAN_INTERVAL_SEC = 3 * 86400  # 每词最小采集间隔：给词 3 天长新帖
RETIRE_STRIKES = 3             # 连续 3 次（≈9 天）会话无新号 → 退役
PROBE_ITEMS = 50               # memo23 首批刺探帖数
DIG_MULTIPLIER = 4             # 深翻倍增倍率：这批出号，下批 maxItems ×4
DIG_MAX_ITEMS = 400            # 单批 maxItems 上限（memo23 无游标，同 maxItems
                               # 重跑只会重复交付同一批最新帖，到顶即换词）

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
    """读 state JSON，缺键补默认值。一次性迁移：旧 zero_streak 是高频
    轮转时代累计的，与现行 3 天 cadence 语义不同，首次加载清零
    （ranch_v1 旗标）。"""
    st: dict = {}
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
        except Exception:
            st = {}
    st.setdefault("offset", 0)
    st.setdefault("daily", {})
    st.setdefault("kw_stats", {})
    st.setdefault("kw_retired", {})
    if not st.get("ranch_v1"):
        for s in st["kw_stats"].values():
            s["zero_streak"] = 0
        st["ranch_v1"] = True
    return st


def record_kw_stat(st: dict, kw: str, n_posts: int, n_new: int) -> None:
    """每词每次会话后记账（SERP+memo23 双源合并）：累计查询/帖/新号，
    维护 last_new_at 与连击（zero_streak=连续无新号会话数）；连击满
    RETIRE_STRIKES 移入 kw_retired 退出轮转。时间戳为北京时间字符串。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    s = st["kw_stats"].setdefault(kw, {"q": 0, "posts": 0, "new": 0,
                                       "first_at": now, "last_q_at": None,
                                       "last_new_at": None, "zero_streak": 0})
    s["q"] += 1
    s["posts"] += n_posts
    s["new"] += n_new
    s["last_q_at"] = now
    if n_new > 0:
        s["last_new_at"] = now
        s["zero_streak"] = 0
        return
    s["zero_streak"] += 1
    retired = st.setdefault("kw_retired", {})
    if s["zero_streak"] >= RETIRE_STRIKES and kw not in retired:
        retired[kw] = {"at": now, "strikes": s["zero_streak"], "q": s["q"]}
        log(f"  ☠「{kw}」连续 {s['zero_streak']} 次会话无新号"
            f"（≈{s['zero_streak'] * SCAN_INTERVAL_SEC // 86400} 天无产出），"
            f"判定枯竭退役，移出轮转")


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
            phones = [p for p in info["phones"]
                      if p.get("bucket") != "overseas"
                      and is_cn_number(p.get("number"), p.get("source"))]
            if not phones:
                continue
            gid = None
            cls = classify_fb_url(link)
            if cls and cls[1] not in NON_GROUP_GIDS:
                gid = cls[1]
            n_new += db.save_fb_contacts(link, gid, phones)
    return n_new


# ---------------------------------------------------------------- memo23

def memo23_search(conn, accounts: list, kw: str,
                  max_items: int) -> list[dict] | None:
    """异步 run + 轮询跑一个关键词，返回 dataset items。
    402/403 欠费记 quota_exhausted_at 并从 accounts 就地移除后换号重试；
    run 超时/FAILED 重试且 maxItems 逐次减半保底（深挖批量大易超时）。
    仍失败返回 None（调用方不记账、该词下轮仍是到期状态）。"""
    mi = max_items
    for attempt in range(3):
        body = json.dumps({"searchType": "posts", "searchQueries": [kw],
                           "maxItems": mi}).encode()
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
        if status == "RUNNING":  # 轮询超时：掐死僵尸 run，别留在平台上计费
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"{APIFY_API}/actor-runs/{run_id}/abort?token={token}",
                    data=b"", method="POST"), timeout=30)
            except Exception:  # noqa: BLE001
                pass
        if status != "SUCCEEDED":
            old = mi
            mi = max(10, mi // 2)  # 降量重试保底
            log(f"  memo23 run「{kw}」状态 {status}（第{attempt + 1}/3次），"
                f"maxItems {old}→{mi} 重试")
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
    return None


# ---------------------------------------------------------------- 落库

def _number_variants(digits: str) -> set[str]:
    """号码规范化候选：纯数字本身 + 86 前缀互转（库里中国号两种形态并存）。"""
    d = re.sub(r"\D+", "", digits or "")
    out = {d}
    if d.startswith("86") and len(d) == 13:
        out.add(d[2:])
    elif re.fullmatch(r"1\d{10}", d):
        out.add("86" + d)
    return out


def filter_known_numbers(conn, phones: list[dict]) -> list[dict]:
    """跨源查重：号码（含 86 变体）已存在 fb_contacts 的剔除，返回新号列表。"""
    fresh = []
    for p in phones:
        variants = _number_variants(p.get("number") or "")
        if not variants:
            continue
        q = ",".join("?" * len(variants))
        row = conn.execute(
            f"SELECT 1 FROM fb_contacts WHERE number IN ({q}) LIMIT 1",
            tuple(variants)).fetchone()
        if row is None:
            fresh.append(p)
    return fresh


def harvest_memo23(db, items: list[dict],
                   seen_urls: set[str] | None = None) -> tuple[int, int]:
    """memo23 帖正文 parse_post 挖中国号落 fb_contacts（group_id=NULL）。
    返回 (有效帖数, 新增号码数)。seen_urls 可跨批传入（深挖批次会重含
    前批帖子，去重后只处理新帖）。"""
    if seen_urls is None:
        seen_urls = set()
    n_posts = n_new = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        text = it.get("text") or ""
        url = it.get("postUrl") or it.get("url") or ""
        if not text or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        n_posts += 1
        info = parse_post(text, text)
        phones = [p for p in info["phones"]
                  if p.get("bucket") != "overseas"
                  and is_cn_number(p.get("number"), p.get("source"))]
        if not phones:
            continue
        phones = filter_known_numbers(db.conn, phones)
        if not phones:
            continue
        n_new += db.save_fb_contacts(url, None, phones,
                                     author=it.get("authorName"))
    return n_posts, n_new


# ---------------------------------------------------------------- 主流程

def pick_due(st: dict, keywords: list[str], limit: int) -> list[str]:
    """从轮转游标起扫一圈，挑出到期词（未退役 且 从未采集或距上次
    ≥ SCAN_INTERVAL_SEC），最多 limit 个；游标推进到最后一个入选词
    之后（一圈都没选到则游标不动）。"""
    n = len(keywords)
    retired = st["kw_retired"]
    now = time.time()
    due, last_i = [], -1
    for i in range(n):
        kw = keywords[(st["offset"] + i) % n]
        if kw in retired:
            continue
        last_q = st["kw_stats"].get(kw, {}).get("last_q_at")
        last_ts = 0.0
        if last_q:
            try:
                last_ts = time.mktime(
                    time.strptime(last_q, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                last_ts = 0.0
        if now - last_ts < SCAN_INTERVAL_SEC:
            continue
        due.append(kw)
        last_i = i
        if len(due) >= limit:
            break
    if last_i >= 0:
        st["offset"] = (st["offset"] + last_i + 1) % n
    return due


def dig_word(db, bd, accounts: list, kw: str, args, st: dict,
             usage: dict, stats: dict) -> bool | None:
    """到期词的完整采集会话：SERP 双引擎各查一页（搜索引擎结果无深挖
    空间，一次到位）+ memo23 刺探最新 50 帖，挖到新号就放大 maxItems
    往深翻（每批 maxItems = 50×批号，重含前批帖子、seen_urls 去重），
    直到某批新号 +0 / 帖空 / 批数到顶。返回 True=会话完成（已记账），
    None=任一路都没跑成（memo23 首批失败且 SERP 未执行，不记账，下轮
    重试）。会话按整体记账：有新号则连击清零，整会话 +0 才记一击。"""
    n_posts = n_new = 0
    recorded = False

    # ---- SERP：Google+Bing 各 1 页 ----
    if usage["serp_queries"] < args.serp_daily_queries:
        q = serp_query(kw)
        for engine in ("google", "bing"):
            if usage["serp_queries"] >= args.serp_daily_queries:
                break
            records = bd.scrape_serp(q, engine=engine)
            usage["serp_queries"] += 1
            stats["serp_queries"] += 1
            save_state(st)
            recorded = True
            n_org = sum(len(r.get("organic") or []) for r in records
                        if isinstance(r, dict) and not r.get("error"))
            n = harvest_serp(db, records)
            n_posts += n_org
            n_new += n
            stats["serp_new"] += n
            log(f"  [serp/{engine}]「{q}」: 结果 {n_org}，新号 +{n}")
            time.sleep(args.delay)
    else:
        log(f"  SERP 当日查询达顶 {args.serp_daily_queries}，跳过该源")

    # ---- memo23：刺探 + 深挖（出号则下批 maxItems ×DIG_MULTIPLIER，封顶 DIG_MAX_ITEMS）----
    if accounts and usage["memo23_results"] < args.memo23_daily_results:
        seen_urls: set[str] = set()
        items_target = PROBE_ITEMS
        batch_no = 0
        while True:
            batch_no += 1
            if not accounts:
                raise AccountError("全部 apify 账号额度耗尽")
            if batch_no > 1 \
                    and usage["memo23_results"] >= args.memo23_daily_results:
                log(f"  memo23 当日结果达顶 {args.memo23_daily_results}，"
                    f"「{kw}」深挖中止")
                break
            items = memo23_search(db.conn, accounts, kw, items_target)
            if items is None:  # 首批失败且 SERP 也没跑成 → 整词不记账
                if batch_no == 1 and not recorded:
                    return None
                break
            recorded = True
            p, n = harvest_memo23(db, items, seen_urls)
            usage["memo23_results"] += len(items)
            stats["memo23_results"] += len(items)
            stats["memo23_new"] += n
            n_posts += p
            n_new += n
            save_state(st)
            tag = "刺探" if batch_no == 1 else f"深翻{batch_no}"
            log(f"  [memo23/{tag}]「{kw}」: 帖 {len(items)}（新帖 {p}），"
                f"新号 +{n}"
                f"（当日 {usage['memo23_results']}/{args.memo23_daily_results}）")
            if n == 0 or not items:
                break  # 这批没挖到新号（或帖空）：挖干了，换下一个词
            if items_target >= DIG_MAX_ITEMS:
                log(f"  「{kw}」深挖达单批上限 {DIG_MAX_ITEMS} 帖仍出号，"
                    f"更深历史留到下周期")
                break
            items_target = min(items_target * DIG_MULTIPLIER, DIG_MAX_ITEMS)
            time.sleep(args.delay)
    elif not accounts:
        log("  memo23 无可用 apify 账号，跳过该源")
    else:
        log(f"  memo23 当日结果达顶 {args.memo23_daily_results}，跳过该源")

    if not recorded:
        return None
    record_kw_stat(st, kw, n_posts, n_new)
    save_state(st)
    log(f"  [fb]「{kw}」会话结束：帖 {n_posts}，新号 +{n_new}，"
        f"连击 {st['kw_stats'][kw]['zero_streak']}/{RETIRE_STRIKES}")
    return True


def run_round(db, bd, accounts: list, keywords: list[str], args,
              st: dict) -> dict:
    """跑一轮：取最多 per-round 个到期词，逐词开采集会话
    （SERP 一遍 + memo23 刺探+深挖）。"""
    usage = today_usage(st)
    stats = {"serp_queries": 0, "serp_new": 0,
             "memo23_results": 0, "memo23_new": 0}
    batch = pick_due(st, keywords, args.per_round)
    if not batch:
        return stats

    for kw in batch:
        if usage["memo23_results"] >= args.memo23_daily_results \
                and usage["serp_queries"] >= args.serp_daily_queries:
            log("  双源当日预算均达顶，本轮提前结束")
            return stats
        ok = dig_word(db, bd, accounts, kw, args, st, usage, stats)
        if ok is None:  # 采集失败：不记账，该词下轮仍到期重试
            time.sleep(args.delay)
            continue
        time.sleep(args.delay)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="FB 关键词直搜采号（memo23+SERP 双源常驻，刺探模式）")
    ap.add_argument("--keywords-file",
                    help="追加关键词文件（一行一个，与内置词库合并去重）")
    ap.add_argument("--per-round", type=int, default=10,
                    help="每轮最多采集几个到期词")
    ap.add_argument("--interval", type=int, default=3600, help="两轮间隔秒数")
    ap.add_argument("--memo23-daily-results", type=int, default=2000,
                    help="memo23 当日结果数上限（缺省 2000 ≈ $3.8/天）")
    ap.add_argument("--serp-daily-queries", type=int, default=400,
                    help="SERP 当日查询数上限")
    ap.add_argument("--delay", type=float, default=5, help="查询间隔秒数")
    ap.add_argument("--once", action="store_true", help="跑一轮即退出")
    args = ap.parse_args()

    keywords = list(KEYWORDS)
    if args.keywords_file:
        for line in Path(args.keywords_file).read_text().splitlines():
            kw = line.strip()
            if kw and kw not in keywords:
                keywords.append(kw)
    log(f"关键词库 {len(keywords)} 个，每词间隔 "
        f"{SCAN_INTERVAL_SEC // 86400} 天，每轮最多 {args.per_round} 个到期词")

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
    if st["kw_retired"]:
        log(f"已退役词 {len(st['kw_retired'])} 个（state.kw_retired），"
            f"不参与轮转")
    # 词库换代后旧 offset 可能越界：对 len(keywords) 取模归一
    if keywords:
        st["offset"] %= len(keywords)
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
        if stats["serp_queries"] or stats["memo23_results"]:
            log(f"本轮：SERP 查询 {stats['serp_queries']} 次新号 +{stats['serp_new']}；"
                f"memo23 结果 {stats['memo23_results']} 条新号 +{stats['memo23_new']}"
                f"（memo23 花费≈${stats['memo23_results'] * MEMO23_COST_PER_RESULT:.3f}）")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
