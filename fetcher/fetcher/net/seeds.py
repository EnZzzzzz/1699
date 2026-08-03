# -*- coding: utf-8 -*-
"""种子身份池（迁移自 scraper/taobao_1688/common.py 的种子段）。

背景：多 worker 化后新出口 IP 一律白板会话启动（防 Cookie 重放），
但白板身份信任分从零，凌晨严格时段首访敏感端点必弹滑块。

解法：种子身份池 —— seeds_dir 下每份 json 是一个「熟身份」
（真实浏览器长期养出的 Cookie，cna/cookie2/t 等设备绑定标识）。
每个 worker 独占认领一份，一对一绑定：
    - 同一身份同时出现在多个 IP = Cookie 重放强信号，一对一独占后不存在；
    - 一个身份顺序地随 IP 轮换迁移 = 真人换网络的弱信号，可接受。
只种设备绑定 Cookie；IP 绑定的安全 Cookie（SECURITY_COOKIE_NAMES）
在加载时剔除，绝不跨 IP 复制。指纹按种子固定（cna 按设备签发，
指纹必须与身份配套）。

烧毁判定（SeedBurnTracker）：同一熟身份在多个新鲜 IP 上首请求即被拦、
或触发登录墙，说明被标记的是身份本身而非 IP —— 判定种子烧毁，
停止播种，退回白板会话。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# 阿里系风控安全 Cookie：由站点按「IP + 设备 + 会话」现场签发，
# 不能跨 IP 复制 —— 把 A 地签发的 x5sec/sgcookie/isg 带到 B 地出口，
# 等于主动告诉风控系统「同一客户端在 IP 池里跳」。
SECURITY_COOKIE_NAMES = frozenset({
    "x5sec", "x5secdata", "x5sectag", "sgcookie", "sg", "isg",
    "unb", "lid", "cookie1", "tracknick", "dnk", "_nk_",
})

# 种子里可保留的验证凭证（仅 seed_x5sec 实验时启用）：
# x5sec/x5secdata 是纯人机验证凭证，种子一对一独占后不存在并发重放；
# 若站点对 x5sec 的校验实际绑设备而非严格绑 IP，保留它可免滑块。
X5SEC_SEEDABLE_NAMES = frozenset({"x5sec", "x5secdata"})


def load_seed_kits(seeds_dir, keep_x5sec: bool = False,
                   domain: str = "1688.com", log=print) -> list[dict]:
    """加载种子身份池：seeds_dir 下每个 .json 是一份 CDP 导出的熟身份 Cookie。

    返回 [{"name": 文件名（去扩展名）, "cookies": [Playwright 格式],
           "x5sec": bool}...]，只保留本站域且非 IP 绑定的设备身份 Cookie；
    keep_x5sec=True 时额外保留未过期的 x5sec/x5secdata（免滑块实验）。
    不含 cna/cookie2 的文件视为「不熟」（和白板没区别），跳过并打日志。
    """
    kits = []
    seeds_dir = Path(seeds_dir)
    if not seeds_dir.exists():
        return kits
    for f in sorted(seeds_dir.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"    [seed] 种子 {f.name} 解析失败，跳过: {e}")
            continue
        cookies, names = [], set()
        for c in raw:
            if domain not in c.get("domain", ""):
                continue
            if c["name"] in SECURITY_COOKIE_NAMES:
                if not (keep_x5sec and c["name"] in X5SEC_SEEDABLE_NAMES):
                    continue  # IP 绑定的安全 Cookie 不跨 IP 复制
                # x5sec 短时效：过期的别种（带过期凭证比不带更可疑）
                exp = c.get("expires") or c.get("expirationDate")
                try:
                    if exp and float(exp) > 0 and float(exp) <= time.time():
                        continue
                except (TypeError, ValueError):
                    continue
            names.add(c["name"])
            cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/") if not c.get("path", "").startswith("//") else "/",
                "secure": bool(c.get("secure", False)),
                "httpOnly": bool(c.get("httpOnly", False)),
            })
        if not ({"cna", "cookie2"} & names):
            log(f"    [seed] 种子 {f.name} 不含 cna/cookie2"
                f"（身份不够熟，和白板没区别），跳过")
            continue
        kits.append({"name": f.stem, "cookies": cookies,
                     "x5sec": bool(X5SEC_SEEDABLE_NAMES & names)})
    return kits


class SeedBurnTracker:
    """种子烧毁判定（行为与旧引擎一致）。

    种子身份在 ≥ burn_threshold 个新鲜 IP 上「首请求即被拦」
    （距上次触发 ≤2 个请求）或触发登录墙（最高级风控，身份嫌疑与
    首请求秒拦同级），判定种子烧毁：停止播种，退回白板会话。
    """

    def __init__(self, kit: dict | None, burn_threshold: int = 2):
        self.kit = kit
        self.burn_threshold = burn_threshold
        self.burn_ips: set = set()

    def note_block(self, identity: str, req_since_block: int,
                   login_wall: bool, log=print) -> bool:
        """记录一次风控触发；返回 True 表示本次调用后种子被判定烧毁。"""
        if self.kit is None:
            return False
        if req_since_block <= 2 or login_wall:
            self.burn_ips.add(identity)
            if len(self.burn_ips) >= self.burn_threshold:
                log(f"    [!] 种子身份「{self.kit['name']}」已在 "
                    f"{len(self.burn_ips)} 个新鲜 IP 上被风控标记"
                    f"（首请求秒拦/登录墙），本 worker 停止播种，"
                    f"后续按白板会话处理（换种子文件可恢复）")
                self.kit = None
                return True
        return False
