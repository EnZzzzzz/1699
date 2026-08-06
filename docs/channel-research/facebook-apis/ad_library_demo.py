#!/usr/bin/env python3
"""Meta Ad Library API (ads_archive) 调研 demo。

按关键词搜索 Meta 广告库，打印广告主 page_name / 广告正文摘要 / ad_snapshot_url，
支持游标分页拉取前 N 条。仅依赖 Python 标准库。

token 从环境变量 META_ACCESS_TOKEN 读取；未设置时打印获取指引后退出。

注意覆盖范围（详见同目录 AD_LIBRARY.md）：
  - 政治/社会议题广告：全球可查（本项目基本用不上）；
  - 商业广告：只有 ad_reached_countries 含欧盟/欧洲经济区国家代码时才会返回
    （DSA 合规要求），查美国等非欧盟市场投放的商业广告 API 一律为空。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/ads_archive"

# 本项目关心商业广告，默认不拉政治广告专属字段（spend/impressions/delivery_by_region）
DEFAULT_FIELDS = [
    "id",
    "page_id",
    "page_name",
    "ad_creation_time",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_snapshot_url",
    "publisher_platforms",
    "languages",
]

TOKEN_GUIDE = """\
未检测到 META_ACCESS_TOKEN 环境变量。获取 token 的步骤（需人工操作）：

  1. 注册 Meta 开发者账号：https://developers.facebook.com （需 Facebook 个人号登录）
  2. 身份确认（必须）：https://www.facebook.com/ID 上传政府签发的身份证件并确认所在国家，
     审核约 1-3 个工作日（中国大陆身份证常被拒，常见做法是用护照/境外主体）。
  3. 创建 App： developers 后台 → My Apps → Create App → 类型选 Business。
  4. 添加产品： App Dashboard → Add Product → 选 "Ad Library API" 并接受条款。
  5. 生成 token： App Dashboard → Tools → Graph API Explorer → 选该 App →
     Generate Access Token（默认短期 token，可用 oauth/access_token 换 60 天长期 token）。
  6. 导出环境变量： export META_ACCESS_TOKEN='EAABsb...'

然后重跑本脚本，例如：
  python3 ad_library_demo.py --query "freight forwarder" --countries DE FR
"""


def api_get(url: str, params: dict | None, retries: int = 3) -> dict:
    """GET 请求并解析 JSON；对限流做指数退避，其他错误打印 Meta 错误体后退出。"""
    for attempt in range(retries):
        full_url = url if params is None else url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full_url, headers={"User-Agent": "ad-library-demo/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(body).get("error", {})
            except json.JSONDecodeError:
                err = {}
            code, msg = err.get("code"), err.get("message", body[:200])
            # code 4/17/613 或 HTTP 429 = 限流，退避后重试
            if e.code == 429 or code in (4, 17, 613):
                wait = 60 * (2 ** attempt)
                print(f"[限流] HTTP {e.code} code={code}，{wait}s 后重试…", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[API 错误] HTTP {e.code} code={code} subcode={err.get('error_subcode')}: {msg}",
                  file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"[网络错误] {e.reason}", file=sys.stderr)
            sys.exit(1)
    print("[失败] 多次限流重试后仍无法完成请求", file=sys.stderr)
    sys.exit(1)


def fetch_ads(token: str, query: str, countries: list[str], max_ads: int,
              per_page: int, active_status: str) -> list[dict]:
    """按关键词拉取广告，游标分页直到凑够 max_ads 或没有下一页。"""
    params = {
        "access_token": token,
        "search_terms": query,
        "ad_reached_countries": json.dumps(countries),  # 形如 ["DE","FR"]
        "ad_type": "ALL",
        "ad_active_status": active_status,
        "fields": ",".join(DEFAULT_FIELDS),
        "limit": min(per_page, 500),
    }
    ads: list[dict] = []
    url, page_params = BASE_URL, params
    while url and len(ads) < max_ads:
        payload = api_get(url, page_params)
        batch = payload.get("data", [])
        ads.extend(batch)
        # 第二页起直接用 paging.next（已含全部参数与游标）
        url = payload.get("paging", {}).get("next")
        page_params = None
        if url and len(ads) < max_ads:
            time.sleep(1)  # 温柔点，配额约 200 calls/user/hour
    return ads[:max_ads]


def print_ad(i: int, ad: dict) -> None:
    body = (ad.get("ad_creative_bodies") or [""])[0].replace("\n", " ")
    if len(body) > 160:
        body = body[:160] + "…"
    platforms = ",".join(ad.get("publisher_platforms") or [])
    print(f"[{i}] {ad.get('page_name', '?')} (page_id={ad.get('page_id', '?')})")
    print(f"    正文: {body or '(无)'}")
    print(f"    平台: {platforms} | 起投: {ad.get('ad_delivery_start_time', '?')}"
          f" | 语言: {','.join(ad.get('languages') or []) or '?'}")
    print(f"    快照: {ad.get('ad_snapshot_url', '?')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Meta Ad Library API 关键词搜索 demo")
    ap.add_argument("--query", default="china sourcing",
                    help="搜索关键词，空格为 AND，引号为短语（默认 'china sourcing'）")
    ap.add_argument("--countries", nargs="+", default=["DE", "FR", "GB"],
                    help="ad_reached_countries 国家代码；查商业广告必须含欧盟国家")
    ap.add_argument("--max-ads", type=int, default=20, help="最多拉取条数（默认 20）")
    ap.add_argument("--per-page", type=int, default=100, help="每页条数（默认 100）")
    ap.add_argument("--active-status", default="ACTIVE",
                    choices=["ACTIVE", "INACTIVE", "ALL"], help="广告在投状态过滤")
    args = ap.parse_args()

    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        print(TOKEN_GUIDE)
        sys.exit(2)

    print(f"搜索: {args.query!r} | 国家: {args.countries} | 状态: {args.active_status}")
    ads = fetch_ads(token, args.query, args.countries, args.max_ads,
                    args.per_page, args.active_status)
    print(f"共拉取 {len(ads)} 条\n")
    for i, ad in enumerate(ads, 1):
        print_ad(i, ad)


if __name__ == "__main__":
    main()
