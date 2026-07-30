#!/usr/bin/env python3
"""
CloakBrowser + 快代理隧道代理 示例

安装:
    pip install cloakbrowser requests
    # 如需根据代理 IP 自动推断时区/语言:
    pip install 'cloakbrowser[geoip]'

首次运行会自动下载隐形 Chromium 二进制 (~200MB，缓存在 ~/.cloakbrowser)。

使用方式:
    1. 在 proxy.py 顶部的 CONFIG 里填入你的 tunnel host:port、用户名、密码；
    2. 运行 python cloak_demo.py。
"""

from cloakbrowser import launch

# 从 proxy.py 引入代理构造函数
from proxy import make_proxies


def get_cloak_proxy() -> str:
    """
    从 proxy.py 获取代理 URL。
    make_proxies() 返回的是 requests 风格的 dict，例如:
        {"http": "http://user:pass@host:port/", "https": "http://user:pass@host:port/"}
    CloakBrowser 需要去掉末尾的斜杠。
    """
    proxies = make_proxies()
    proxy_url = proxies["https"].rstrip("/")
    print(f"[代理] 使用隧道代理: {proxy_url}")
    return proxy_url


def main():
    proxy_url = get_cloak_proxy()

    # 启动 CloakBrowser，走代理并开启反检测增强配置
    browser = launch(
        headless=False,          # 有头模式，部分站点对 headless 更敏感
        humanize=True,           # 拟人鼠标/键盘/滚动
        proxy=proxy_url,         # 快代理隧道代理
        geoip=True,              # 根据代理出口 IP 自动匹配 timezone + locale
    )

    page = browser.new_page()

    # 访问目标站点
    url = "https://www.baidu.com"
    print(f"正在访问: {url}")
    page.goto(url, wait_until="networkidle")

    # 打印页面标题和关键指纹信息
    title = page.title()
    ua = page.evaluate("() => navigator.userAgent")
    webdriver = page.evaluate("() => navigator.webdriver")
    timezone = page.evaluate("() => Intl.DateTimeFormat().resolvedOptions().timeZone")
    language = page.evaluate("() => navigator.language")

    print(f"页面标题: {title}")
    print(f"User-Agent: {ua}")
    print(f"navigator.webdriver: {webdriver}")  # 正常应为 False/None
    print(f"浏览器时区: {timezone}")
    print(f"浏览器语言: {language}")

    # 截图保存
    screenshot_path = "cloak_demo.png"
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"截图已保存: {screenshot_path}")

    browser.close()


if __name__ == "__main__":
    main()
