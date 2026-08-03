# -*- coding: utf-8 -*-
"""Session：一个 worker 当前持有的浏览器会话及其链路身份。

会话链路一致性（迁移自 scraper/taobao_1688/common.py 的设计）：
    Cookie / UA / 指纹 / 出口 IP 四者必须配套。identity 即出口 IP
    （直连记 "direct"），Cookie 按 identity 隔离存取；指纹种子按
    identity（或种子身份名）固定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 避免 core -> net 的反向依赖
    from fetcher.net.proxy.base import Channel


@dataclass
class Session:
    """一次浏览器启动的产物。

    browser/page 为 Playwright 对象（Any 以保持本包可独立 import，
    不依赖 playwright 安装）。
    """

    browser: Any = None
    page: Any = None
    identity: str = "direct"          # 出口 IP；直连记 "direct"
    channel: "Channel | None" = None  # 代理通道；直连为 None
    req_proxies: dict | None = None   # requests 查询出口 IP 用的代理字典
    seed_kit: dict | None = None      # 本会话播种的种子身份（{"name","cookies","x5sec"}）
    extra: dict = field(default_factory=dict)  # 站点/任务层暂存

    @property
    def ctx(self):
        """Playwright BrowserContext（page.context 的快捷方式）。"""
        return self.page.context if self.page is not None else None

    @property
    def use_proxy(self) -> bool:
        return self.channel is not None and self.channel.server is not None

    def close(self, store=None, log=None):
        """关闭会话：先回写 Cookie（给了 store 时），再关浏览器。

        任何退出路径都应走这里，保证服务端会话租约及时释放、
        Cookie 信任链不丢。
        """
        if store is not None and self.page is not None:
            try:
                cookies = [c for c in self.ctx.cookies()]
                if cookies:
                    store.save(self.identity, cookies)
            except Exception as e:  # noqa: BLE001 - 回写失败不阻断关闭
                if log:
                    log(f"[!] 旧 Cookie 回写失败: {e}")
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001
                pass
