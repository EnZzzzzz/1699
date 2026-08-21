#!/usr/bin/env python3
# 关键词健康报表：读 X/FB 两个脚本的 state JSON 里的 kw_stats（只读），
# 按词展示采集表现与老化状态，供换词决策使用。
# 用法：
#   python3 scraper/kw_stats.py            # FB/X 两张表，枯竭在前
#   python3 scraper/kw_stats.py --aging    # 只列枯竭/老化词（换词候选）
#   python3 scraper/kw_stats.py --top 20   # 按累计新号产量排序
# 状态判据：退役（X 脚本判真枯竭已移出轮转，见 state.kw_retired）>
# 回扫中（X 回扫未完成）> 枯竭（>7 天无新号且查询≥5）>
# 老化（3~7 天无新号或连续+0≥10）> 活跃（3 天内出过新号）>
# 观察（查询 <5 次还没出过新号）> 未启用（词库里有但没查过）。
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fetcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fb_keyword_search import KEYWORDS as FB_BUILTIN  # noqa: E402
from x_keyword_search import X_KEYWORDS as X_BUILTIN  # noqa: E402

CACHE = REPO_ROOT / ".cache"
FMT = "%Y-%m-%d %H:%M:%S"

# 状态排序权重（越小越靠前）
SEVERITY = {"退役": 0, "枯竭": 1, "老化": 2, "回扫中": 3, "观察": 4,
            "活跃": 5, "未启用": 6}


def load_json(name: str) -> dict:
    p = CACHE / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def load_words(fname: str, builtin: list[str], override: bool) -> list[str]:
    """override=True（X）：文件存在则整体覆盖内置；否则（FB）内置+文件合并。"""
    p = CACHE / fname
    extra = [l.strip() for l in p.read_text().splitlines()
             if l.strip()] if p.exists() else []
    if override and extra:
        return extra
    out = list(builtin)
    for w in extra:
        if w not in out:
            out.append(w)
    return out


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, FMT)
    except ValueError:
        return None


def kw_status(channel: str, kw: str, s: dict | None, backfill: dict,
              now: datetime, backfill_active: bool = False,
              retired: dict | None = None) -> str:
    if retired and kw in retired:
        return "退役"
    if channel == "x":
        bf = backfill.get(kw)
        # 有明确回扫进度，或回扫期刚开始、该词还没排上（无记录）都算回扫中
        if bf not in (None, "done") or (bf is None and backfill_active):
            return "回扫中"
    if s is None:
        return "未启用"
    ln = parse_time(s.get("last_new_at"))
    days = (now - ln).days if ln else None
    if ln and days is not None and days <= 3:
        return "活跃"
    if s.get("new", 0) == 0 and s.get("q", 0) < 5:
        return "观察"
    if (days is None or days > 7) and s.get("q", 0) >= 5:
        return "枯竭"
    return "老化"


def build_rows(channel: str, words: list[str], kw_stats: dict,
               backfill: dict, now: datetime,
               retired: dict | None = None) -> list[dict]:
    # 回扫期是否进行中（存在未完成进度记录）：进行中时，X 词无记录视为待扫
    backfill_active = any(v != "done" for v in backfill.values())
    rows = []
    for kw in words:
        s = kw_stats.get(kw)
        rows.append({
            "kw": kw,
            "q": s.get("q", 0) if s else 0,
            "posts": s.get("posts", 0) if s else 0,
            "new": s.get("new", 0) if s else 0,
            "last_new": (s.get("last_new_at") or "—") if s else "—",
            "zero": s.get("zero_streak", 0) if s else 0,
            "status": kw_status(channel, kw, s, backfill, now,
                                backfill_active, retired),
        })
    return rows


def render(channel: str, rows: list[dict], args) -> None:
    if args.aging:
        rows = [r for r in rows if r["status"] in ("退役", "枯竭", "老化")]
    if args.top:
        rows = sorted(rows, key=lambda r: -r["new"])[:args.top]
    else:
        rows = sorted(rows, key=lambda r: (SEVERITY[r["status"]], -r["zero"],
                                           -r["q"]))
    title = "FB" if channel == "fb" else "X"
    print(f"\n## {title}（{len(rows)} 词）\n")
    print("| 关键词 | 查询 | 帖 | 新号 | 最后出新号 | 连续+0 | 状态 |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        kw = r["kw"] if len(r["kw"]) <= 40 else r["kw"][:37] + "..."
        print(f"| {kw} | {r['q']} | {r['posts']} | {r['new']} "
              f"| {r['last_new']} | {r['zero']} | {r['status']} |")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = " / ".join(f"{k} {v}" for k, v in
                         sorted(counts.items(), key=lambda x: SEVERITY[x[0]]))
    print(f"\n{title} 汇总：{summary}")


def main() -> int:
    ap = argparse.ArgumentParser(description="关键词健康报表（只读 state JSON）")
    ap.add_argument("--aging", action="store_true", help="只列枯竭/老化词")
    ap.add_argument("--top", type=int, default=0, help="按累计新号排序取前 N")
    args = ap.parse_args()

    now = datetime.now()
    fb_st = load_json("fb_keyword_search_state.json")
    x_st = load_json("x_keyword_search_state.json")

    fb_words = load_words("fb_keywords_extra.txt", FB_BUILTIN, override=False)
    x_words = load_words("x_keywords_all.txt", X_BUILTIN, override=True)

    render("fb", build_rows("fb", fb_words, fb_st.get("kw_stats", {}), {},
                            now), args)
    render("x", build_rows("x", x_words, x_st.get("kw_stats", {}),
                           x_st.get("kw_backfill", {}), now,
                           x_st.get("kw_retired", {})), args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
