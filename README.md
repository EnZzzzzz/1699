# 1688 采集平台

1688 / FB / X 采集与数据管理系统，本机单机部署。

## 组成

```
platform/     管理系统（前后端分离）
  server/     FastAPI 后端（端口 8765）：看板 / 数据浏览 / 供应商 / health
  web/        React 18 + Vite + TS + Tailwind + shadcn/ui 前端（端口 3000）
  start.sh    一键启动后端+前端；stop.sh 停止
.cache/1688.db  SQLite 主库（WAL 模式）：shops / contacts / fb_contacts / providers 等
scraper/ util/  独立脚本。常驻采集只跑两个直搜脚本：
                scraper/fb_keyword_search.py（FB 关键词直搜采号）
                scraper/x_keyword_search.py（X 关键词直搜采号）
wa-check/     WhatsApp 登录态存档（auth_info-xiaohao-4/5 等，当前无代码使用，勿删）
docs/         channel-research/（渠道调研）· made-in-china-scraping.md
```

## 启动

```bash
cd platform && ./start.sh     # 前端 http://127.0.0.1:3000，后端 http://127.0.0.1:8765
cd platform && ./stop.sh      # 停止
```

## 功能页面

| 页面 | 说明 |
|---|---|
| 整体看板 | FB / X 采号总数与速率（置顶）、WA 查号转化、1688 店铺采集管道 |
| 数据浏览 | 店铺/联系人筛选分页，WhatsApp 注册状态筛选 |
| 供应商 | 代理池与第三方 API 凭证管理、通道同步、并发探测出口 IP |

主题：浅色/深色/跟随系统，设计 token 集中于 `platform/web/src/styles/tokens.css`。

## WhatsApp 查号

走 `scraper/wa_check_apify.py`（Apify 查注册态，回写 fb_contacts，欠费自动轮换账号）。

## 文档

- [docs/channel-research/facebook-groups.md](docs/channel-research/facebook-groups.md)：FB 渠道现行方案与运行结论
- [docs/made-in-china-scraping.md](docs/made-in-china-scraping.md)：联系方式采集源调研（中国制造网中文站可采，含爬取方案）
