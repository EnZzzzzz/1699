#!/usr/bin/env python3
"""Meta Graph API 最小 demo（仅依赖标准库）。

演示三件事：
  (a) GET /me                —— 验证 token 是否有效
  (b) GET /me/accounts       —— 列出当前用户有角色的 Page（及对应 Page Token）
  (c) GET /{page_id}/posts   —— 读指定 Page 的帖子（自己的 Page 用 pages_read_engagement
                               即可；别人的 Page 需要 App Review 通过的
                               Page Public Content Access 特性）

用法：
  export META_ACCESS_TOKEN="EAAG..."
  python3 graph_api_demo.py                 # (a)+(b)
  python3 graph_api_demo.py <page_id>       # 追加执行 (c)
  # 或用环境变量指定 Page：META_PAGE_ID=123456 python3 graph_api_demo.py

无 token 时打印获取指引并以退出码 1 退出。
调研结论与 token 获取步骤见同目录 README.md。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# 当前最新 stable 版本（2026-02-18 发布），见官方 changelog：
# https://developers.facebook.com/docs/graph-api/changelog
API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


def graph_get(path, params):
    """发起一次 Graph API GET 请求，返回 (data, error) 二元组。"""
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "graph-api-demo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # 速率限制用量在响应头里（X-App-Usage / X-Business-Use-Case-Usage）
            usage = resp.headers.get("X-App-Usage") or resp.headers.get(
                "X-Business-Use-Case-Usage"
            )
            if usage:
                print(f"  [rate-limit header] {usage}")
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read().decode("utf-8")).get("error", {})
        except Exception:
            return None, {"message": f"HTTP {e.code}", "code": e.code}
    except urllib.error.URLError as e:
        return None, {"message": f"网络错误: {e.reason}"}


def print_error(step, err):
    print(f"  ✗ {step} 失败: (#{err.get('code')}) {err.get('message')}")
    print(f"    type={err.get('type')} fbtrace_id={err.get('fbtrace_id')}")


GUIDE = """\
未检测到 META_ACCESS_TOKEN 环境变量。

获取一个可用的 User Access Token 的最快路径（用于本 demo）：

  1. 注册 Meta 开发者账号：https://developers.facebook.com/ （需要 Facebook 账号）
  2. 创建应用：https://developers.facebook.com/apps → Create App
     → 用例选 "Other" → 类型选 "Business"（Business 类型才能拿 Page 相关权限）
  3. 打开 Graph API Explorer：https://developers.facebook.com/tools/explorer/
     - 右上角选中刚创建的应用
     - "Add a Permission" 里勾选：pages_show_list、pages_read_engagement
       （这两个权限在 Standard Access 下对「你在应用里有角色」的账号免审可用）
     - 点 "Generate Access Token"，完成授权弹窗，复制得到的 User Token
  4. 导出环境变量后重跑本脚本：
       export META_ACCESS_TOKEN="EAAG..."

注意：
  - Graph API Explorer 生成的是短期 token（约 1-2 小时），过期需重新生成；
    长期 token（约 60 天）需用 app secret 走 /oauth/access_token 换发。
  - 读「别人的 Page」的帖子需要 Page Public Content Access 特性，
    该特性要 Advanced Access（Business Verification + App Review），
    采集类用途基本不会被批准——这正是本项目主路线不走 Graph API 的原因。
"""


def main():
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        print(GUIDE)
        return 1

    auth = {"access_token": token}

    # (a) 验证 token
    print("== (a) GET /me 验证 token ==")
    data, err = graph_get("me", {"fields": "id,name", **auth})
    if err:
        print_error("/me", err)
        return 2
    print(f"  ✓ token 有效: id={data.get('id')} name={data.get('name')}")

    # (b) 列出自己有角色的 Page（返回里带每个 Page 的 Page Access Token）
    print("\n== (b) GET /me/accounts 列自己的 Page ==")
    data, err = graph_get(
        "me/accounts", {"fields": "id,name,category,tasks", "limit": 25, **auth}
    )
    if err:
        print_error("/me/accounts", err)
        print("  提示: 需要 pages_show_list 权限，且 token 属于在应用里有角色的用户")
    else:
        pages = data.get("data", [])
        if not pages:
            print("  （该账号下没有 Page，或未授予 pages_show_list 权限）")
        for p in pages:
            print(f"  - {p.get('name')}  id={p.get('id')}  category={p.get('category')}")

    # (c) 读指定 Page 的 posts
    page_id = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("META_PAGE_ID", "")).strip()
    if not page_id:
        print("\n== (c) 跳过：未提供 page_id（命令行参数或 META_PAGE_ID）==")
        return 0
    print(f"\n== (c) GET /{page_id}/posts 读 Page 帖子 ==")
    data, err = graph_get(
        f"{page_id}/posts",
        {"fields": "id,message,created_time,permalink_url", "limit": 10, **auth},
    )
    if err:
        print_error(f"/{page_id}/posts", err)
        print("  提示: 读自己的 Page 需 pages_read_engagement；")
        print("        读别人的 Page 需 Page Public Content Access（App Review，难过审）")
        return 3
    for post in data.get("data", []):
        msg = (post.get("message") or "").replace("\n", " ")[:60]
        print(f"  - [{post.get('created_time')}] {post.get('id')}")
        print(f"    {msg}")
        print(f"    {post.get('permalink_url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
