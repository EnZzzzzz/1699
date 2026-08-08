# -*- coding: utf-8 -*-
"""IdentityStore：Cookie 按出口 IP（identity）隔离存取。

包一层 ShopDB 的 Cookie 语义，作为网络层的唯一 Cookie 出入口：
    - 会话链路一致性要求 Cookie 与出口 IP 不错配（代理模式与直连
      模式的 Cookie 分开存取）；
    - load 自动剔除已过期 Cookie；save 保留过期时间；
    - burn 用于登录墙等最高级风控标记后清空身份，避免已烧毁会话
      随 IP 轮换复活；
    - 直连模式的 JSON 种子导入也走这里（domain 过滤可配）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fetcher.db import ShopDB


class IdentityStore:
    """按 identity 隔离的 Cookie 存取（ShopDB 语义封装）。"""

    def __init__(self, db: ShopDB, domain: str = "1688.com"):
        self.db = db
        self.domain = domain  # 只存取该站域下的 Cookie

    # ---- 基本存取 ----

    def load(self, identity: str) -> list[dict]:
        """加载某 identity 下未过期的 Cookie（Playwright 格式）。"""
        return self.db.load_cookies(identity)

    def save(self, identity: str, cookies: list[dict]) -> int:
        """保存 Cookie（按 identity+domain+path+name UPSERT 覆盖）。"""
        return self.db.save_cookies(identity, cookies)

    def burn(self, identity: str) -> int:
        """清空某 identity 名下全部 Cookie（会话身份已被最高级标记，
        如登录墙）：旧 Cookie 留着只会让轮换回来的 IP 复活已烧毁的会话。"""
        return self.db.delete_cookies(identity)

    def info(self, identity: str) -> dict:
        """数量/已过期数/最近过期时间（日志用）。"""
        return self.db.cookie_info(identity)

    # ---- IP 事件（透传 ShopDB 统计，评估代理 IP 质量用） ----

    def record_event(self, identity: str, event: str, detail: str = "",
                     req_since_block: int | None = None) -> None:
        self.db.record_ip_event(identity, event, detail, req_since_block)

    def stat_request(self, identity: str, ok: bool = False) -> None:
        self.db.ip_stat_request(identity, ok=ok)

    def stat_block(self, identity: str) -> None:
        self.db.ip_stat_block(identity)

    # ---- 从浏览器上下文回写 ----

    def save_from_context(self, identity: str, ctx, log=print,
                          domain: str | None = None) -> int:
        """把浏览器上下文中的本站 Cookie 写回（含新签发的 x5sec 等）。

        迁移自 common.save_cookies：每次过证/成功/退出时调用，
        保证下次启动时 Cookie 与同一出口 IP 链路一致。
        domain 参数：按指定域过滤（None 时回落 self.domain）；
        多站点场景 per-view 域过滤用。
        """
        filter_domain = domain if domain is not None else self.domain
        cookies = [c for c in ctx.cookies()
                   if filter_domain in c.get("domain", "")]
        if not cookies:
            return 0
        n = self.save(identity, cookies)
        log(f"    [cookie] 已把 {n} 个 Cookie 写回数据库 (identity={identity})")
        return n

    # ---- 直连模式 JSON 种子 ----

    def seed_from_json(self, identity: str, cookie_path: Path) -> int:
        """把 CDP 导出的 JSON Cookie 作为种子导入（保留过期时间）。

        仅供直连模式（identity='direct'）：Cookie 是本机 IP 下签发的，
        链路一致，全量保留。代理模式的新出口 IP 不播种（避免把匿名身份
        标识跨 IP 复制形成 Cookie 重放特征）。
        """
        raw = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
        seeds = [c for c in raw if self.domain in c.get("domain", "")]
        return self.save(identity, seeds)


def load_cookies_pw(cookie_path: Path, domain: str = "1688.com") -> list[dict]:
    """把 CDP 导出的 Cookie 转成 Playwright 格式（仅指定域）。

    仅用于把 .cache/cookies_1688.json 作为种子导入 SQLite；
    日常运行以数据库 cookies 表为准。
    """
    raw = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
    cookies = []
    for c in raw:
        d = c.get("domain", "")
        if domain not in d:
            continue
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": d,
            "path": c.get("path", "/") if not c.get("path", "").startswith("//") else "/",
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly", False)),
        })
    return cookies
