# -*- coding: utf-8 -*-
"""
1688 Cookie 有效性验证脚本

用从浏览器导出的 Cookie 请求 1688 首页，验证：
1. HTTP 状态码是否为 200
2. 最终落地 URL 是否还是首页（没有被重定向到验证码/登录页）
3. 响应内容是否包含首页特征（而非滑块验证页特征）

用法:
    python3 verify_1688.py

注意（会话链路一致性）:
    Cookie 是从本机真实浏览器导出的，出口 IP 为本机 IP。
    因此本脚本直连请求（不走快代理代理），保持 Cookie / UA /
    出口 IP 一致，避免触发 x5sec 风控。低频率、单请求验证。
"""

import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("缺少 requests 库，请先: pip3 install requests")

BASE_DIR = Path(__file__).resolve().parent
COOKIE_JSON = BASE_DIR / ".cache" / "cookies_1688.json"

# 与导出 Cookie 时的浏览器保持一致
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/150.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# 滑块/风控页特征关键词
BLOCK_SIGNS = ["x5sec", "punish", "验证码", "滑块", "sec.taobao.com",
               "login.1688.com", "请登录"]
# 首页正常特征
OK_SIGNS = ["1688", "阿里巴巴"]


def load_cookies() -> dict:
    """从导出的 JSON 构建 1688 域名下的 Cookie 字典。"""
    cookies = json.loads(COOKIE_JSON.read_text(encoding="utf-8"))
    jar = {}
    for c in cookies:
        domain = c.get("domain", "")
        # 只带 1688 相关域，避免泄露其他站点凭据
        if "1688.com" in domain or domain.endswith(".alibaba.com"):
            jar[c["name"]] = c["value"]
    return jar


def main() -> int:
    if not COOKIE_JSON.exists():
        sys.exit(f"找不到 Cookie 文件: {COOKIE_JSON}")

    cookies = load_cookies()
    print(f"[1] 已加载 {len(cookies)} 个 1688 域名 Cookie")
    print(f"    关键字段: cna={'cna' in cookies}, "
          f"unb={'unb' in cookies}, "
          f"x5sec={'x5sec' in cookies}")

    session = requests.Session()
    session.headers.update(HEADERS)

    url = "https://www.1688.com/"
    try:
        resp = session.get(url, cookies=cookies, timeout=15,
                           allow_redirects=True)
    except requests.RequestException as e:
        sys.exit(f"[X] 请求失败: {e}")

    print(f"[2] HTTP 状态码: {resp.status_code}")
    print(f"[3] 最终 URL: {resp.url}")
    print(f"[4] 响应大小: {len(resp.content)} bytes")

    body = resp.text

    # 判断是否被风控
    blocked = [s for s in BLOCK_SIGNS if s in body or s in resp.url]
    ok = [s for s in OK_SIGNS if s in body]

    print(f"[5] 命中首页特征: {ok if ok else '无'}")
    if blocked:
        print(f"[X] 疑似被风控/要求登录, 命中: {blocked}")
        return 1

    if resp.status_code == 200 and "1688.com" in resp.url and ok:
        # 提取 title 佐证
        import re
        m = re.search(r"<title>(.*?)</title>", body, re.S)
        title = m.group(1).strip() if m else "(未找到)"
        print(f"[6] 页面标题: {title}")
        print("[OK] 验证通过: Cookie 有效, 1688 首页可正常打开!")
        return 0

    print("[X] 验证失败: 状态码或内容异常")
    return 1


if __name__ == "__main__":
    sys.exit(main())
