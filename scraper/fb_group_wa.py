# -*- coding: utf-8 -*-
"""fb_group_wa.py — FB 群帖联系方式采集 + WhatsApp 注册验证（独立快脚本）。

用法：
    # 全自动：自己发现帖子 → 抓取 → 查号（发现层走 DuckDuckGo，无需 key）
    python3 scraper/fb_group_wa.py
    python3 scraper/fb_group_wa.py --keywords "外贸 whatsapp" "货代 微信" --pages 2
    # 手动：直接给帖子 URL
    python3 scraper/fb_group_wa.py <帖子URL> [更多URL...]
    python3 scraper/fb_group_wa.py --urls-file urls.txt

流程（依据 docs/channel-research/facebook-groups.md 的实测结论）：
    0. 发现层：DDG html 端点裸抓 SERP（复用 fetcher 的 FetchDdgSerp 解析纯函数），
       查询词矩阵 `site:facebook.com/groups <关键词>`，解析出帖 permalink。
       DDG 限流形态为 ~2 连查后 202，故查询间节奏强制 ≥60s、202 退避 180~240s；
       重试仍被限时走 Apify Google Search Scraper 付费兜底（$1.8~4.5/1K 页，
       --apify-budget 控制本轮上限，缺省 $0.5，0 关闭）。
    1. CloakBrowser 匿名渲染群帖 permalink（纯 HTTP 会被 TLS 指纹 400，必须浏览器）
    2. 提取 og:description + DOM 正文，复用 fetcher 的 parse_post 正则分桶：
       - declared_wa  自声明 WA 号（wa.me 链接 / 紧邻 WhatsApp 标签）→ 默认不查，标记 declared
       - cn_uncertain 其余中国手机号 → 过 wa_check 协议查号
       - overseas     非 +86 国际号 → 默认不查（--check-overseas 开启）
    3. wa_check 走 fetcher/vendor/wa-check 的 Node/Baileys CLI（需已扫码登录的
       auth_info-<account>/，默认账号 xiaohao-4）
    4. 统一落库 .cache/1688.db（--no-db 关闭）：fb_posts（发现溯源+状态回写）、
       fb_contacts（号码分桶，number UNIQUE 幂等）、查号结果回写 wa_registered
       ——与 daemon 同口径，落库后 daemon 的 wa_check topup 会自动接力查
       cn_uncertain 桶的号。号码状态用 bucket/wa_source/wa_registered 三列
       区分（自声明确定/待查/海外暂缓/已验证）；抓过的帖 URL 记入 seen
       文件 + fb_posts，跨运行去重
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# 复用 fetcher 包的提取/解析纯函数（fetcher/fetcher/ 是真正的包目录）
sys.path.insert(0, str(REPO_ROOT / "fetcher"))

from fetcher.sites.facebook.post import parse_post  # noqa: E402
from fetcher.atoms.facebook_discover import (  # noqa: E402
    MIN_SAMPLE_FLOOR, BLOCK_BACKOFF_MIN, BLOCK_BACKOFF_MAX,
    parse_serp_results, classify_fb_url,
)
from fetcher.net.browser import wait_for_license_seat  # noqa: E402

WA_CHECK_DIR = REPO_ROOT / "fetcher" / "vendor" / "wa-check"
DEFAULT_ACCOUNT = "xiaohao-4"

# ---- 发现层：DDG html 端点（与 fetcher.atoms.facebook_discover 同口径）----
DDG_HTML = "https://html.duckduckgo.com/html/"
DDG_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# 默认关键词矩阵（docs/channel-research/facebook-groups.md §7 的侦察矩阵
# + 2026-08-10 扩词：原 10 词 SERP 结果被采干，新增细分品类/英文词扩新帖源）
DEFAULT_KEYWORDS = [
    "外贸 whatsapp",
    "货代 whatsapp",
    "跨境电商 whatsapp",
    "亚马逊卖家 微信",
    "外贸 微信",
    "货代 微信",
    "china sourcing whatsapp",
    "外贸资源 whatsapp",
    "外贸 +86",
    "chat.whatsapp.com 外贸",
    # ---- 扩词（第二轮起生效）----
    "海运 whatsapp",
    "双清包税 whatsapp",
    "中东专线 whatsapp",
    "非洲专线 whatsapp",
    "海外仓 whatsapp",
    "亚马逊测评 whatsapp",
    "广交会 whatsapp",
    "sourcing agent whatsapp",
    "import from china whatsapp",
    "dropshipping whatsapp",
    # ---- 扩词（2026-08-10 第三轮：新能源/大型机械/汽车配件）----
    "新能源 whatsapp",
    "锂电池 whatsapp",
    "光伏 whatsapp",
    "solar panel whatsapp",
    "ev charger whatsapp",
    "大型机械 whatsapp",
    "工程机械 whatsapp",
    "heavy machinery whatsapp",
    "汽车配件 whatsapp",
    "auto parts whatsapp",
    "汽配 微信",
]

# ---- 匿名硬拦截特征（摘自 fetcher/sites/facebook/features.py，内联保持脚本独立）----
LOGIN_URL_PATTERNS = ("facebook.com/login", "/login.php", "facebook.com/checkpoint")
BLOCK_TEXT_KEYWORDS = (
    "You're Temporarily Blocked", "You’re Temporarily Blocked",
    "misusing this feature", "You can't use this feature",
    "你暂时无法使用", "操作过于频繁",
)
CONTENT_UNAVAILABLE_KEYWORDS = (
    "This content isn't available", "content isn't available right now",
    "此内容当前不可用", "内容不可用", "The link you followed may be broken",
)

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
_JS_SCROLL_DOWN = "() => window.scrollTo(0, document.body.scrollHeight)"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_license_key() -> str | None:
    """CloakBrowser license：环境变量优先，.cache/config.json 兜底。"""
    key = os.environ.get("CLOAKBROWSER_LICENSE_KEY")
    if key:
        return key
    cfg = REPO_ROOT / ".cache" / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:  # noqa: BLE001
            return None
    return None


def block_reason(page, text: str) -> str | None:
    """匿名硬拦截判定：302 登录墙 / 频率限制整页文案。"""
    url = page.url or ""
    for pat in LOGIN_URL_PATTERNS:
        if pat in url:
            return f"跳登录墙（{url}）"
    for kw in BLOCK_TEXT_KEYWORDS:
        if kw in text:
            return f"频率限制页（{kw}）"
    return None


# ---------------------------------------------------------------- 发现层

def ddg_query(query: str, page: int = 1, timeout: int = 30) -> tuple[int, str]:
    """DDG html 端点裸 GET，返回 (status, html)。"""
    url = f"{DDG_HTML}?q={urllib.parse.quote(query)}&s={(page - 1) * 10}"
    req = urllib.request.Request(url, headers={
        "User-Agent": DDG_UA,
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
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        # 传输层错误（SSL EOF/连接重置/超时等网络抖动）：返回 -1 由调用方
        # 跳过本查询，不让单次抖动打死整个发现循环
        log(f"    DDG 请求失败（{type(e).__name__}: {e}）")
        return -1, ""


# ---- 发现层兜底：Apify Google Search Scraper（付费，DDG 限流时启用）----
# 调研结论（docs/channel-research/facebook-summary.md §1）：发现层外包
# Google SERP $1.8~4.5/1K 查询页，远低于抓取外包；按 $0.0045/页保守计费。
APIFY_GS_ACTOR = "apify~google-search-scraper"
APIFY_API = "https://api.apify.com/v2"
APIFY_PAGE_COST = 0.0045


def load_apify_token(db) -> str | None:
    """从 providers 表读 apify token（db 为空时直开 SQLite 读）。"""
    import sqlite3
    try:
        conn = db.conn if db is not None else sqlite3.connect(
            str(REPO_ROOT / ".cache" / "1688.db"), timeout=30)
        row = conn.execute(
            "SELECT config_json FROM providers WHERE kind='apify' "
            "OR name='apify' LIMIT 1").fetchone()
        return json.loads(row[0]).get("api_token") if row else None
    except Exception as e:  # noqa: BLE001
        log(f"[!] 读 apify token 失败（{e}），兜底通道不可用")
        return None


def _apify_run(payload: dict, token: str, timeout: int) -> list[dict]:
    """调 run-sync-get-dataset-items 返回原始 items。

    传输层抖动（SSL EOF/重置/超时）自动重试一次再上抛，HTTP 错误
    （4xx/5xx）原样上抛由调用方处置。注意 run-sync 端点硬上限 300s。
    """
    url = (f"{APIFY_API}/acts/{APIFY_GS_ACTOR}/run-sync-get-dataset-items"
           f"?token={token}&timeout={timeout}")
    for attempt in range(2):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            raise                      # 业务错误（402/429 等）不重试
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 1:
                raise
            log("    Apify 请求网络抖动，20s 后重试…")
            time.sleep(20)
    return []


def apify_google_query(query: str, max_pages: int, token: str,
                       timeout: int = 180) -> list[dict]:
    """同步调 Google Search Scraper，返回 [{"url","title"}...]（有机结果）。

    一次调用抓 max_pages 页；resultsPerPage 实测给到 100 也只回 ~10 条/
    页（2026-08-10 实测），召回量只能靠 maxPagesPerQuery。
    """
    payload = {"queries": query, "maxPagesPerQuery": max_pages,
               "resultsPerPage": 10}
    items = _apify_run(payload, token, timeout)
    out: list[dict] = []
    for it in items or []:
        for r in it.get("organicResults") or []:
            if r.get("url"):
                out.append({"url": r["url"], "title": r.get("title") or ""})
    return out


def apify_google_batch(keywords: list[str], max_pages: int,
                       token: str) -> dict[str, list[dict]]:
    """一个 run 跑全部关键词（queries 换行分隔、actor 内 maxConcurrency 并行），
    返回 {kw: [{"url","title"}...]}。按页计费与逐词拆 run 相同，但省掉
    逐词 run 的启动与串行等待（31 词 × 1 页实测 ~1 分钟，2026-08-10）。
    """
    prefix = "site:facebook.com/groups "
    payload = {"queries": "\n".join(prefix + kw for kw in keywords),
               "maxPagesPerQuery": max_pages, "resultsPerPage": 10,
               "maxConcurrency": 10}
    items = _apify_run(payload, token, timeout=280)
    out: dict[str, list[dict]] = {}
    for it in items or []:
        term = (it.get("searchQuery") or {}).get("term") or ""
        kw = term[len(prefix):] if term.startswith(prefix) else term
        for r in it.get("organicResults") or []:
            if r.get("url"):
                out.setdefault(kw, []).append(
                    {"url": r["url"], "title": r.get("title") or ""})
    return out


def discover_post_urls(keywords: list[str], pages: int,
                       seen: set[str], max_posts: int, db=None,
                       apify_token: str | None = None,
                       apify_budget: float = 0.0,
                       apify_only: bool = False) -> list[dict]:
    """DDG 发现帖 permalink：关键词矩阵 × 页码，查询间 ≥60s、202 退避。

    返回 [{"url","group_id","group_name","keyword"}...]（去重，跳过 seen
    里已抓过的）。db 非空时每查一页就立即落 fb_posts（INSERT OR IGNORE
    幂等），进程中途崩也不丢已发现的帖。中途达到 max_posts 仍把当前
    查询页解析完再停。

    混合模式：DDG 重试后仍非 200 且 apify_budget 有余额时，改用 Apify
    Google Search Scraper 一次抓满该关键词全部 pages 页（记入账本，
    同关键词后续页不再重复付费）；Apify 报 402/连续出错则本轮停用兜底。
    apify_only=True 时完全不直连 DDG，且全部关键词合成一个 Apify run
    批量发现（actor 内并行），预算不足时按序截断关键词。
    """
    found: list[dict] = []
    found_urls: set[str] = set()

    def harvest(kw: str, serp: list[dict], source: str, tag: str) -> None:
        """从一页/一词 SERP 结果里筛新帖、落 fb_posts、并入 found。"""
        page_posts: list[dict] = []
        for r in serp:
            cls = classify_fb_url(r["url"])
            if not cls or cls[0] != "post":
                continue
            url = r["url"]
            if url in seen or url in found_urls:
                continue
            found_urls.add(url)
            page_posts.append({"url": url, "group_id": cls[1],
                               "group_name": r["title"], "keyword": kw})
        found.extend(page_posts)
        if db is not None and page_posts:
            db.save_fb_posts(keyword=kw, source=source, posts=page_posts)
        log(f"    「{kw}」{tag}[{source}]：{len(page_posts)} 个新帖"
            f"（累计 {len(found)}）")

    if apify_only:
        # 批量发现：一次 run 抓满全部关键词 × pages 页，成本按页预付
        per_kw = pages * APIFY_PAGE_COST
        kws = keywords[:int(apify_budget // per_kw)] if per_kw > 0 else []
        if len(kws) < len(keywords):
            log(f"    [!] 预算 ${apify_budget:.2f} 只够 {len(kws)}/"
                f"{len(keywords)} 个关键词，其余本轮跳过")
        if not kws:
            return []
        try:
            by_kw = apify_google_batch(kws, pages, apify_token)
        except urllib.error.HTTPError as e:
            log(f"    [!] Apify 批量发现失败（HTTP {e.code}），本轮发现层放弃")
            return []
        except Exception as e:  # noqa: BLE001
            log(f"    [!] Apify 批量发现异常（{type(e).__name__}: {e}），"
                f"本轮发现层放弃")
            return []
        apify_spent = len(kws) * per_kw
        log(f"    Apify 批量发现：{len(kws)} 词 × {pages} 页，"
            f"花费约 ${apify_spent:.3f}/${apify_budget:.2f}")
        for kw in kws:
            if len(found) >= max_posts:
                break
            harvest(kw, by_kw.get(kw, []), "apify_gs", f"{pages}页")
        log(f"本轮 Apify 发现层花费约 ${apify_spent:.3f}")
        return found[:max_posts]

    queries = [(kw, p) for kw in keywords for p in range(1, pages + 1)]
    apify_spent = 0.0
    apify_covered: set[str] = set()   # 已由 Apify 抓满全部页的关键词
    apify_strikes = 0                 # 兜底通道连续出错计数（≥3 本轮停用）
    for i, (kw, page) in enumerate(queries):
        if len(found) >= max_posts:
            break
        q = f"site:facebook.com/groups {kw}"
        status, html = ddg_query(q, page)
        if status == 202:  # anomaly 限流：退避覆盖 ~4 分钟封禁窗口后重试一次
            wait = random.uniform(BLOCK_BACKOFF_MIN, BLOCK_BACKOFF_MAX)
            log(f"    DDG 限流（202），退避 {wait:.0f}s 后重试…")
            time.sleep(wait)
            status, html = ddg_query(q, page)
        serp: list[dict] = []
        source = "ddg"
        if status == 200:
            serp = parse_serp_results(html)
        elif (apify_token and apify_budget > 0 and apify_strikes < 3
                and kw not in apify_covered
                and apify_spent + pages * APIFY_PAGE_COST <= apify_budget):
            # DDG 此 IP 已被限死 → 付费兜底：一次抓满该关键词全部页
            try:
                serp = apify_google_query(q, pages, apify_token)
                apify_covered.add(kw)
                apify_spent += pages * APIFY_PAGE_COST
                source = "apify_gs"
                log(f"    「{q}」DDG HTTP {status} → Apify 兜底抓 "
                    f"{pages} 页：{len(serp)} 条有机结果"
                    f"（本轮已花 ${apify_spent:.3f}/{apify_budget:.2f}）")
            except urllib.error.HTTPError as e:
                if e.code == 402:
                    apify_strikes = 3
                    log("    [!] Apify 余额不足（402），本轮停用付费兜底")
                else:
                    apify_strikes += 1
                    log(f"    Apify 兜底失败（HTTP {e.code}），"
                        f"连续失败 {apify_strikes}/3")
            except Exception as e:  # noqa: BLE001
                apify_strikes += 1
                log(f"    Apify 兜底异常（{type(e).__name__}: {e}），"
                    f"连续失败 {apify_strikes}/3")
        if status != 200 and not serp:
            note = "（Apify 已覆盖该词全部页，跳过）" if kw in apify_covered else ""
            log(f"    「{q}」第{page}页：HTTP {status}，跳过{note}")
        else:
            harvest(kw, serp, source, f"第{page}页")
        # 查询间节奏（最后一次查询后不必等）
        if i < len(queries) - 1 and len(found) < max_posts:
            wait = random.uniform(MIN_SAMPLE_FLOOR, MIN_SAMPLE_FLOOR + 20)
            log(f"    …查询间隔 {wait:.0f}s（DDG 防限流）")
            time.sleep(wait)
    if apify_spent:
        log(f"本轮 Apify 发现层花费约 ${apify_spent:.3f}")
    return found[:max_posts]


# ---------------------------------------------------------------- 抓取

def scrape_post(page, url: str, timeout_ms: int = 60000) -> dict:
    """渲染抓一个群帖 permalink，返回 {status, ...提取结果}。"""
    rec: dict = {"url": url, "status": "ok", "title": "", "phones": [],
                 "wa_group_invites": [], "wechat_ids": [], "tg_handles": []}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(random.uniform(2.0, 4.0))
        text = page.evaluate(_JS_BODY_TEXT) or ""
        reason = block_reason(page, text)
        if reason:
            rec["status"] = f"blocked: {reason}"
            return rec
        # 滚一屏触发评论懒加载（评论留号是机会增量，渲染有随机性）
        try:
            page.evaluate(_JS_SCROLL_DOWN)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(1.5, 2.5))

        og = page.evaluate(_JS_OG) or {}
        text = page.evaluate(_JS_BODY_TEXT) or ""
        for kw in CONTENT_UNAVAILABLE_KEYWORDS:
            if kw in text:
                rec["status"] = f"empty: 帖子内容不可用（{kw}）"
                return rec
        info = parse_post(og.get("description", ""), text)
        rec.update(title=og.get("title", ""), **info)
        return rec
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"error: {str(e).splitlines()[0][:150]}"
        return rec


# ---------------------------------------------------------------- 查号

def to_e164(number: str, bucket: str) -> str:
    """中国桶裸 11 位补 86；declared/overseas 已带国家码，原样纯数字。"""
    d = re.sub(r"\D+", "", number)
    if bucket == "cn_uncertain" and re.fullmatch(r"1\d{10}", d):
        d = "86" + d
    return d


def wa_check(numbers: list[str], account: str,
             delay_min: float = 1.5, delay_max: float = 3.0) -> dict[str, dict]:
    """批量查号，返回 {e164: {"registered": bool|None, "jid"/"error": ...}}。"""
    if not numbers:
        return {}
    auth_dir = WA_CHECK_DIR / f"auth_info-{account}"
    if not auth_dir.is_dir():
        log(f"[!] wa-check 账号「{account}」未登录（缺 {auth_dir.name}/），跳过查号。"
            f"登录：cd {WA_CHECK_DIR} && node check.js --auth={account} <任意号码>")
        return {}
    cli = WA_CHECK_DIR / "check.js"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(numbers))
        list_path = f.name
    results_path = tempfile.mktemp(suffix=".json", prefix="wa_results_")
    timeout = (60 + len(numbers) * (delay_max + 5)) * 1.2 + 120
    env = dict(os.environ,
               WA_AUTH_DIR=str(auth_dir), WA_RESULTS=results_path,
               WA_DELAY_MIN=str(delay_min), WA_DELAY_MAX=str(delay_max))
    log(f"…WhatsApp 查号 {len(numbers)} 个（账号 {account}，逐号间隔 "
        f"{delay_min:g}~{delay_max:g}s）")
    try:
        proc = subprocess.run(
            ["node", str(cli), list_path], cwd=str(WA_CHECK_DIR), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout)
        for line in proc.stdout.splitlines():
            s = line.strip()
            if s and not s.startswith('{"level":'):  # 过滤 Baileys 内部日志
                log(f"  {s}")
        if proc.returncode != 0:
            log(f"[!] check.js 退出码 {proc.returncode}，查号失败")
            return {}
        with open(results_path, encoding="utf-8") as f:
            results = json.load(f).get("results", [])
        return {re.sub(r"\D+", "", str(r.get("number", ""))): r for r in results}
    except subprocess.TimeoutExpired:
        log(f"[!] 查号超时（>{timeout:.0f}s）")
        return {}
    finally:
        for p in (list_path, results_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(
        description="FB 群帖联系方式采集 + WhatsApp 注册验证"
                    "（不给 URL 时自动走 DDG 发现层）")
    ap.add_argument("urls", nargs="*", help="群帖 permalink（/groups/{gid}/posts/{pid}/）")
    ap.add_argument("--urls-file", help="帖子 URL 列表文件（每行一个，# 开头为注释）")
    ap.add_argument("--keywords", nargs="+", default=None,
                    help="发现层关键词（缺省内置 10 词矩阵；自动加 site:facebook.com/groups 前缀）")
    ap.add_argument("--pages", type=int, default=1, help="每个关键词翻页数（缺省 1）")
    ap.add_argument("--max-posts", type=int, default=100,
                    help="本轮最多抓多少个新帖（缺省 100）")
    ap.add_argument("--seen-file", default="fb_wa_seen.txt",
                    help="已抓帖 URL 记录文件，跨运行去重（缺省 fb_wa_seen.txt；"
                         "落库时 fb_posts 也会并入去重集）")
    ap.add_argument("--no-db", action="store_true",
                    help="不写 SQLite（缺省落库 .cache/1688.db 的 fb_posts/"
                         "fb_contacts；daemon 的 wa_check 队列会接力查号）")
    ap.add_argument("--account", default=DEFAULT_ACCOUNT,
                    help=f"wa-check 账号名（缺省 {DEFAULT_ACCOUNT}）")
    ap.add_argument("--no-check", action="store_true",
                    help="只提取不查号（declared_wa 也标 declared）")
    ap.add_argument("--verify-declared", action="store_true",
                    help="自声明 WA 号也过 wa_check 终验（默认信任声明不查）")
    ap.add_argument("--check-overseas", action="store_true",
                    help="海外号（非 +86）也查（默认跳过）")
    ap.add_argument("--headed", action="store_true", help="有头运行（调试用）")
    ap.add_argument("--delay", type=float, nargs=2, metavar=("MIN", "MAX"),
                    default=(3.0, 6.0), help="帖间随机间隔秒（缺省 3~6）")
    ap.add_argument("--apify-budget", type=float, default=0.5, metavar="USD",
                    help="发现层 Apify Google SERP 兜底的本轮花费上限美元"
                         "（缺省 0.5；0 = 关闭兜底纯 DDG）")
    ap.add_argument("--apify-only", action="store_true",
                    help="发现层完全不直连 DDG，全部走 Apify Google SERP"
                         "（需 token，花费仍受 --apify-budget 限制）")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.urls_file:
        for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    # ---- DB（缺省落库 .cache/1688.db；ShopDB 自带 WAL + busy_timeout 30s，
    #      与 daemon 同库并发安全。落库后 daemon 的 wa_check topup 会自动
    #      接力查 cn_uncertain 桶的号，脚本内查号是互补）----
    db = None
    if not args.no_db:
        try:
            from fetcher.db import ShopDB  # 延迟导入
            db = ShopDB()
        except Exception as e:  # noqa: BLE001
            log(f"[!] 数据库打开失败（{e}），本轮只写文件")
            db = None

    # ---- 0. 发现层：没给 URL 时自动发现 ----
    seen_path = Path(args.seen_file)
    seen: set[str] = set()
    if seen_path.exists():
        seen = {l.strip() for l in seen_path.read_text().splitlines() if l.strip()}
    if db is not None:
        seen |= {r[0] for r in db.conn.execute("SELECT url FROM fb_posts")}
    meta: dict[str, dict] = {}   # url -> {"group_id","group_name","keyword"}
    if not urls:
        keywords = args.keywords or DEFAULT_KEYWORDS
        apify_token = (load_apify_token(db)
                       if args.apify_budget > 0 or args.apify_only else None)
        if args.apify_only and not apify_token:
            log("[!] --apify-only 需要 providers 表里的 apify token，未读到，退出")
            return 1
        if args.apify_only and args.apify_budget <= 0:
            log("[!] --apify-only 下 --apify-budget 必须 > 0（否则发现层无可用通道）")
            return 1
        mode = "Apify-only（跳过 DDG 直连）" if args.apify_only else "DDG 节奏 ≥60s/查询"
        log(f"未发现帖子 URL，自动发现：{len(keywords)} 个关键词 × "
            f"{args.pages} 页（{mode}，已抓过 {len(seen)} 帖跳过"
            f"；Apify 预算 ${args.apify_budget:.2f}"
            f"{'，token 就绪' if apify_token else '，无 token 关闭'}）")
        found = discover_post_urls(keywords, args.pages, seen,
                                   args.max_posts, db=db,
                                   apify_token=apify_token,
                                   apify_budget=args.apify_budget,
                                   apify_only=args.apify_only)
        log(f"发现 {len(found)} 个新帖")
        if not found:
            log("[!] 没有发现新帖，结束")
            return 1
        urls = [p["url"] for p in found]
        for p in found:
            meta[p["url"]] = p
        # fb_posts 已在发现循环内逐页落库（崩了也不丢）
    else:
        for u in urls:
            cls = classify_fb_url(u)
            meta[u] = {"group_id": cls[1] if cls else None,
                       "group_name": "", "keyword": "manual"}
        if db is not None:
            db.save_fb_posts(keyword="manual", source="manual", posts=[
                {"url": u, "group_id": meta[u]["group_id"], "group_name": ""}
                for u in urls])
    urls = list(dict.fromkeys(urls))

    from cloakbrowser import launch as cloak_launch  # 重依赖延迟导入

    def open_browser():
        # 上次异常退出会残留会话席位租约，新二进制会被服务端拒绝（表现为
        # launch 后浏览器自行退出）——启动前先等席位释放（与 daemon 同口径）
        wait_for_license_seat(log=log)
        log(f"启动 CloakBrowser（{'有头' if args.headed else '无头'}）…")
        b = cloak_launch(headless=not args.headed,
                         license_key=load_license_key(),
                         locale="zh-CN", timezone="Asia/Shanghai")
        return b, b.new_context().new_page()

    browser, page = open_browser()

    # ---- 1. 逐帖抓取 ----
    posts: list[dict] = []
    relaunches = 0
    try:
        for i, url in enumerate(urls, 1):
            log(f"[{i}/{len(urls)}] {url}")
            rec = scrape_post(page, url)
            # 浏览器死亡（残留席位被拒/进程崩溃）：重启浏览器重试本帖，最多 2 次
            while "has been closed" in rec["status"] and relaunches < 2:
                relaunches += 1
                log(f"    浏览器已关闭，重启重试（第 {relaunches} 次）…")
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
                browser, page = open_browser()
                rec = scrape_post(page, url)
            n = len(rec["phones"])
            log(f"    {rec['status']}" +
                (f"（{n} 个号码：{rec['title'][:40]}）" if n else ""))
            posts.append(rec)
            if db is not None:
                # 号码落 fb_contacts（number UNIQUE 幂等；declared_wa 桶
                # wa_source='declared'）+ fb_posts 回写状态——与 daemon 的
                # FbPostTask 同口径，落库后 daemon wa_check topup 会接力查号
                gid = meta.get(url, {}).get("group_id")
                if rec["status"] == "ok":
                    n_new = db.save_fb_contacts(url, gid, rec["phones"])
                    db.mark_fb_post_done(url, has_contact=bool(
                        rec["phones"] or rec["wa_group_invites"]
                        or rec["wechat_ids"] or rec["tg_handles"]))
                    if n_new:
                        log(f"    fb_contacts 新增 {n_new} 个号码")
                elif not rec["status"].startswith("error:"):
                    # blocked/empty 置 failed 可溯源；error（浏览器/导航层）
                    # 保持 pending 留给后续重跑
                    db.mark_fb_post_failed(url)
            if i < len(urls):
                time.sleep(random.uniform(*args.delay))
    finally:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass

    # 抓过的 URL 记入 seen（含失败/被拦的，避免反复撞死帖）
    with open(seen_path, "a", encoding="utf-8") as f:
        for rec in posts:
            if rec["url"] not in seen:
                f.write(rec["url"] + "\n")

    # ---- 2. 汇总号码并按分层策略分桶 ----
    # contacts: e164 -> 汇总记录
    contacts: dict[str, dict] = {}
    for rec in posts:
        for p in rec["phones"]:
            e164 = to_e164(p["number"], p["bucket"])
            c = contacts.setdefault(e164, {
                "number": e164, "bucket": p["bucket"], "source": p["source"],
                "wa_registered": None, "post_urls": []})
            if rec["url"] not in c["post_urls"]:
                c["post_urls"].append(rec["url"])

    to_check = [e164 for e164, c in contacts.items()
                if not args.no_check
                and (c["bucket"] == "cn_uncertain"
                     or (args.verify_declared and c["bucket"] == "declared_wa")
                     or (args.check_overseas and c["bucket"] == "overseas"))]

    # ---- 3. wa_check ----
    results = wa_check(to_check, args.account) if to_check else {}
    for e164, c in contacts.items():
        if e164 in results:
            c["wa_registered"] = results[e164].get("registered")
        elif c["bucket"] == "declared_wa" and not args.verify_declared:
            c["wa_registered"] = "declared"  # 自声明，未协议验证
        else:
            c["wa_registered"] = "unchecked"

    # 查号结果回写 fb_contacts（与 daemon wa_task 同口径：wa_registered
    # 三态 + wa_checked_at + wa_source='checked'；库里中国号存裸 11 位，
    # e164 的 86 前缀需剥掉匹配）
    if db is not None and results:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        n_wb = 0
        for e164, r in results.items():
            reg = r.get("registered")
            if reg is None:
                continue
            candidates = [e164, e164[2:] if e164.startswith("86") else "86" + e164]
            marks = ",".join("?" * len(candidates))
            cur = db.conn.execute(
                f"UPDATE fb_contacts SET wa_registered=?, wa_checked_at=?,"
                f" wa_source='checked' WHERE number IN ({marks})",
                (1 if reg else 0, ts, *candidates))
            n_wb += cur.rowcount
        db.conn.commit()
        log(f"fb_contacts 查号回写 {n_wb} 行")

    # ---- 4. 汇总（数据统一在 fb_contacts，按 bucket/wa_source/wa_registered
    #    三列区分状态：declared_wa+wa_source='declared' = 自声明确定；
    #    cn_uncertain+wa_checked_at IS NULL = 待查；overseas = 海外暂缓）----
    n_ok = sum(1 for p in posts if p["status"] == "ok")
    n_checked_reg = sum(1 for c in contacts.values() if c["wa_registered"] is True)
    n_not_reg = sum(1 for c in contacts.values() if c["wa_registered"] is False)
    n_declared = sum(1 for c in contacts.values() if c["wa_registered"] == "declared")
    n_pending = sum(1 for c in contacts.values()
                    if c["wa_registered"] == "unchecked"
                    and c["bucket"] == "cn_uncertain")
    n_overseas = sum(1 for c in contacts.values() if c["bucket"] == "overseas")
    log(f"完成：{n_ok}/{len(posts)} 帖抓取成功，本轮 {len(contacts)} 个唯一号码：")
    log(f"  ✓ 已注册（协议验证）: {n_checked_reg}")
    log(f"  ✓ 已注册（自声明）  : {n_declared}")
    log(f"  ✗ 未注册            : {n_not_reg}")
    log(f"  ? 待查（cn_uncertain）: {n_pending}"
        + ("（已落库，wa 账号恢复后由 daemon 接力查）" if n_pending else ""))
    log(f"  - 海外暂缓           : {n_overseas}")
    if db is not None:
        row = db.conn.execute(
            "SELECT COUNT(*), SUM(wa_registered=1) FROM fb_contacts").fetchone()
        log(f"fb_contacts 全库：{row[0]} 个号码，已注册 {row[1] or 0}")
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
