# 1688 采集平台

1688 / 义乌购采集与管理系统，本机单机部署。

## 组成

```
fetcher/      采集框架（Python 包）：网络层 / 原子能力层 / 判断层 / 策略层 / 站点插件层
              CLI：python -m fetcher 1688 shop|contact|company / yiwugo search / taobao search
platform/     管理系统（前后端分离）
  server/     FastAPI 后端（任务监督器 subprocess、SSE 日志、供应商与 WhatsApp 账号管理）
  web/        React 18 + Vite + TS + Tailwind + shadcn/ui 前端
  start.sh    一键启动（后端 8765 + 前端 3000 + 调度器 daemon）；stop.sh 停止
.cache/1688.db  SQLite 主库（shops/contacts/tasks/providers/proxy_channels/task_events 等）
scraper/ util/  旧版脚本，可独立运行
```

## 启动

```bash
cd platform && ./start.sh     # 前端 http://127.0.0.1:3000，后端 http://127.0.0.1:8765
                              # 同时拉起调度器 daemon（fetcher daemon，消费 work_items 队列）
cd platform && ./stop.sh      # 停止（含 daemon 优雅退出）
```

**重要**：平台已纳管调度器 daemon（start.sh 自动拉起、stop.sh 优雅停止），
**不要再手动启动** `python -m fetcher daemon`（会双 daemon 抢队列）。daemon
运行日志见 `platform/logs/daemon.log`，运行状态可在前端「调度器」看板查看。

后端 venv 重建要点见 `platform/server/requirements.txt` 头部注释
（fetcher 需 `pip install --no-deps -e ../../fetcher`）。

## 功能页面

| 页面 | 说明 |
|---|---|
| 整体看板 | 店铺四状态 / 联系人统计 / pending 积压 / 采集 vs 消耗速率 / 逐小时对比图 |
| 任务管理 | 创建并启停 1688 shop/contact、义乌购搜索、WhatsApp 查号任务，SSE 实时日志 |
| 供应商 | 青果配置管理、通道同步、并发探测出口 IP |
| WhatsApp 账号 | 扫码登录（二维码实时上屏）、多账号隔离管理 |
| 数据浏览 | 店铺/联系人筛选分页，WhatsApp 注册状态筛选 |

主题：浅色/深色/跟随系统，设计 token 集中于 `platform/web/src/styles/tokens.css`。

## WhatsApp 查号

原子能力 `fetcher.atoms.CheckWhatsApp`，协议实现为内置 Node/Baileys CLI
（`fetcher/vendor/wa-check/`）。会话凭证在 `auth_info[-账号名]/`（已 gitignore），
多账号完全隔离，可并发分摊风控。首次登录需手机扫码（管理平台 WhatsApp 账号页
可直接完成）。注意：协议查询违反 WhatsApp ToS，建议使用备用小号。

## 历史文档

- [docs/flow-architecture.md](docs/flow-architecture.md)：fetcher 框架设计
- [docs/service-architecture.md](docs/service-architecture.md)：旧服务化方案（未实施，存档）
- [docs/made-in-china-scraping.md](docs/made-in-china-scraping.md)：联系方式采集源调研（中国制造网中文站可采，含爬取方案）
