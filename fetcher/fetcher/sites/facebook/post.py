# -*- coding: utf-8 -*-
"""Facebook 群帖联系方式提取（纯函数，便于单测）。

输入 og:description + DOM 正文（两者同页取得，og 截断 ~200 字符，DOM 是
全文含首屏评论），输出按查号分层策略（docs/channel-research/
facebook-groups.md §8）分桶的联系方式：

    declared_wa    自声明 WA 号：wa.me/<号> 或紧邻 WhatsApp/ws 标签的号码
    cn_uncertain   其余中国手机号（裸号/微信标签，需过 wa_check）
    overseas       其余国际号（非 +86，独立分桶暂缓查号）

号码口径：中国手机号存裸 11 位（与 1688 contacts 一致，86 由 wa 链路补）；
国际号存纯数字（保留原文国家码，不带 +）。自声明 WA 号保留原文国家码
——提取阶段已按显式 +CC 定归属国，避免 normalize_numbers 把 11 位 1
开头的国际号误补 86（§8 已知缺陷）。

号码正则的分隔符只含空格/制表/短横/括号，**不含换行**：实测 DOM 正文里
号码后紧跟换行+点赞数（"+8618118711701\\n1"），允许换行会把 UI 计数
误并进号码。
"""

from __future__ import annotations

import re

_NUM = r"\+?[0-9][0-9 \t\-()]{5,18}[0-9]"   # 不含换行的号码片段

RE_WA_ME = re.compile(rf"(?i)wa\.me/({_NUM})")
RE_WA_GROUP = re.compile(r"(?i)chat\.whatsapp\.com/([A-Za-z0-9]{10,})")
RE_WA_LABELED = re.compile(
    rf"(?i)\b(?:whats\s*app|ws)\b\s*[：:]?\s*({_NUM})")
RE_CN_MOBILE = re.compile(r"(?<![\d+])1[3-9]\d{9}(?!\d)")
RE_INTL = re.compile(r"(\+[0-9][0-9 \t\-()]{5,18}[0-9])")
RE_WECHAT = re.compile(
    r"(?i)(?:微信|薇信|wechat|wx|vx)\s*[：:]\s*([A-Za-z0-9][\w\-]{4,19})")
# 「微信138xxx」无冒号直连手机号形态（实测样本存在；限定数字避免误吞中文）
RE_WECHAT_MOBILE = re.compile(r"(?:微信|薇信)\s*(1[3-9]\d{9})(?!\d)")
RE_V_MOBILE = re.compile(r"(?<![A-Za-z0-9_])[Vv](1[3-9]\d{9})(?!\d)")
RE_TG = re.compile(r"(?i)(?:tg|telegram|电报)\s*[：:]\s*@?([A-Za-z][\w]{3,31})")
RE_TME = re.compile(r"(?i)t\.me/([A-Za-z][\w]{3,31})")

BUCKET_DECLARED_WA = "declared_wa"
BUCKET_CN_UNCERTAIN = "cn_uncertain"
BUCKET_OVERSEAS = "overseas"

_DIGITS = re.compile(r"\D+")


def _digits(s: str) -> str:
    return _DIGITS.sub("", s or "")


def _last11(digits: str) -> str:
    return digits[-11:]


def _dedup(items) -> list:
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def parse_post(og_desc: str, body_text: str) -> dict:
    """从 og:description + DOM 正文提取联系方式并分桶（纯函数）。

    返回 {
        "phones":           [{"number","bucket","source"}...]（去重保序），
        "wa_group_invites": [chat.whatsapp.com 邀请码...],
        "wechat_ids":       [微信/薇信 标签后的 id...]（含 V+手机号形态），
        "tg_handles":       [TG 标签/t.me 用户名...],
    }
    """
    text = f"{og_desc or ''}\n{body_text or ''}"

    # ---- 1. 自声明 WA 号（wa.me 链接 + WA 标签邻近号）----
    declared: list[tuple[str, str]] = []   # (digits, source)
    for m in RE_WA_ME.finditer(text):
        d = _digits(m.group(1))
        if 8 <= len(d) <= 15:
            declared.append((d, "wa_me"))
    for m in RE_WA_LABELED.finditer(text):
        d = _digits(m.group(1))
        if 8 <= len(d) <= 15:
            declared.append((d, "wa_label"))
    declared_keys = {_last11(d) for d, _ in declared}

    phones: list[dict] = []
    seen11: set[str] = set()

    def _add(digits: str, bucket: str, source: str) -> None:
        key = _last11(digits)
        if key in seen11:
            return
        seen11.add(key)
        phones.append({"number": digits, "bucket": bucket, "source": source})

    for d, src in declared:
        _add(d, BUCKET_DECLARED_WA, src)

    # ---- 2. 国际号：+86 归中国桶（取裸 11 位），其余归海外桶 ----
    for m in RE_INTL.finditer(text):
        d = _digits(m.group(1))
        if not (8 <= len(d) <= 15) or _last11(d) in declared_keys:
            continue
        if d.startswith("86") and len(d) == 13:
            _add(d[2:], BUCKET_CN_UNCERTAIN, "intl_cc86")
        else:
            _add(d, BUCKET_OVERSEAS, "intl")

    # ---- 3. 裸中国手机号 ----
    for m in RE_CN_MOBILE.finditer(text):
        d = m.group(0)
        if _last11(d) in declared_keys:
            continue
        _add(d, BUCKET_CN_UNCERTAIN, "bare_cn")

    return {
        "phones": phones,
        "wa_group_invites": _dedup(RE_WA_GROUP.findall(text)),
        "wechat_ids": _dedup(RE_WECHAT.findall(text)
                             + RE_WECHAT_MOBILE.findall(text)
                             + RE_V_MOBILE.findall(text)),
        "tg_handles": _dedup(RE_TG.findall(text) + RE_TME.findall(text)),
    }
