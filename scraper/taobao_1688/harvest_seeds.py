#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
种子收割：从 .cache/1688.db 的 cookies 表里，把「已经养熟的身份」
自动导出为种子文件，放进 .cache/seeds/ 供下次运行一对一认领。

「熟」的判定：
    - 该 identity（出口 IP）在 ip_stats 里有成功抓取记录（ok > 0）
      —— 证明这套身份在真实抓取中通过过风控、积累了站内轨迹
    - 名下持有 cna 或 cookie2（设备身份标识）

导出规则（与 common.load_seed_kits 的过滤口径一致）：
    - 只留 1688 域的设备身份 Cookie；剔除与会话安全上下文深度绑定的
      sgcookie/sg/isg/x5sectag，但**保留 x5sec/x5secdata**（纯验证凭证，
      是否实际播种由运行时 --seed-x5sec 开关决定）
    - 按 cna 值去重：同一设备身份可能挂在多个出口 IP 名下，
      保留最近更新的一份；seeds 目录里已有种子包含的 cna 也跳过
    - 文件名 = 原 identity（出口 IP）：引擎按种子名固定浏览器指纹，
      以原 IP 命名恰好复现该身份当初养成时的指纹（指纹与身份配套）

用法:
    python3 harvest_seeds.py            # 收割并写入 .cache/seeds/
    python3 harvest_seeds.py --dry-run  # 只列出能收割哪些，不写文件
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import SECURITY_COOKIE_NAMES, X5SEC_SEEDABLE_NAMES
from database import ShopDB

ROOT_DIR = Path(__file__).resolve().parents[2]
SEEDS_DIR = ROOT_DIR / ".cache" / "seeds"


def existing_seed_cnas(seeds_dir: Path) -> set[str]:
    """已有种子文件里的 cna 值（避免收割出重复身份）。"""
    cnas = set()
    for f in seeds_dir.glob("*.json"):
        try:
            for c in json.loads(f.read_text(encoding="utf-8")):
                if c.get("name") == "cna":
                    cnas.add(c.get("value", ""))
        except Exception:
            pass
    return cnas


def harvest(db: ShopDB) -> list[dict]:
    """找出可收割的熟身份，按 cna 去重（保留最近更新的）。"""
    rows = db.conn.execute(
        """SELECT c.identity, c.name, c.value, c.domain, c.path,
                  c.secure, c.http_only, c.expires, c.updated_at,
                  s.ok, s.requests
           FROM cookies c
           JOIN ip_stats s ON s.identity = c.identity
           WHERE s.ok > 0
           ORDER BY c.updated_at DESC""").fetchall()
    by_identity: dict[str, dict] = {}
    for r in rows:
        slot = by_identity.setdefault(
            r["identity"],
            {"identity": r["identity"], "ok": r["ok"],
             "requests": r["requests"], "updated_at": r["updated_at"],
             "cookies": [], "cna": None})
        if r["name"] in SECURITY_COOKIE_NAMES \
                and r["name"] not in X5SEC_SEEDABLE_NAMES:
            continue  # IP 绑定的安全 Cookie 不进种子
                    # （x5sec/x5secdata 保留，是否使用由 --seed-x5sec 决定）
        if "1688.com" not in (r["domain"] or ""):
            continue
        slot["cookies"].append({
            "name": r["name"], "value": r["value"], "domain": r["domain"],
            "path": r["path"] or "/", "secure": bool(r["secure"]),
            "httpOnly": bool(r["http_only"]), "expires": r["expires"],
        })
        if r["name"] == "cna":
            slot["cna"] = r["value"]
        slot["updated_at"] = max(slot["updated_at"], r["updated_at"])

    kits = []
    seen_cna: set[str] = set()
    for slot in by_identity.values():
        names = {c["name"] for c in slot["cookies"]}
        if not ({"cna", "cookie2"} & names):
            continue  # 不熟
        if slot["cna"] and slot["cna"] in seen_cna:
            continue  # 同一设备身份，已有更新的副本
        if slot["cna"]:
            seen_cna.add(slot["cna"])
        kits.append(slot)
    kits.sort(key=lambda k: k["updated_at"], reverse=True)
    return kits


def main() -> int:
    ap = argparse.ArgumentParser(description="从 1688.db 收割养熟的身份为种子文件")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出可收割的身份，不写文件")
    ap.add_argument("--seeds-dir", type=str, default=str(SEEDS_DIR),
                    help=f"种子输出目录（默认 {SEEDS_DIR}）")
    args = ap.parse_args()

    seeds_dir = Path(args.seeds_dir)
    db = ShopDB()
    kits = harvest(db)
    db.close()
    if not kits:
        print("[seed] 数据库里没有可收割的熟身份"
              "（需要有成功抓取记录且持有 cna/cookie2 的 identity）")
        return 0

    known_cnas = existing_seed_cnas(seeds_dir)
    written = 0
    for k in kits:
        if k["cna"] and k["cna"] in known_cnas:
            print(f"    - {k['identity']}: cna 已在现有种子中，跳过")
            continue
        names = sorted({c["name"] for c in k["cookies"]})
        print(f"    ✓ {k['identity']}: 成功 {k['ok']}/{k['requests']} 次，"
              f"{len(k['cookies'])} 个设备 Cookie（{', '.join(names[:6])}"
              f"{'...' if len(names) > 6 else ''}）")
        if args.dry_run:
            continue
        seeds_dir.mkdir(parents=True, exist_ok=True)
        # 文件名 = 原出口 IP：复现该身份养成时的浏览器指纹
        out = seeds_dir / f"{k['identity']}.json"
        out.write_text(json.dumps(k["cookies"], ensure_ascii=False,
                                  indent=2), encoding="utf-8")
        print(f"      -> {out}")
        written += 1
    if not args.dry_run:
        print(f"[seed] 共收割 {written} 份种子到 {seeds_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
