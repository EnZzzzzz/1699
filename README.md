# 1688 采集平台（服务化版）

前后端分离的 1688 店铺/联系方式采集平台，本机单机部署。

- 设计文档：[docs/service-architecture.md](docs/service-architecture.md)
- 旧版 CLI 脚本保留在 `scraper/`、`util/`，可独立运行，与新服务互不依赖

## 架构

```
web/    React 18 + Vite + TS + Tailwind + shadcn/ui 前端（5 个页面）
server/ FastAPI + Celery + Redis + SQLite 后端
        ├─ ProxyPoolManager：全局共享代理通道池（acquire/release、FIFO 排队、心跳回收）
        ├─ Provider 抽象：青果网络已接入，新厂商加一个 provider 模块即可
        ├─ Celery tasks：crawl.shop_crawl / crawl.contact_fetch
        └─ WebSocket /ws：任务进度 + IP 池状态实时推送（断线降级轮询）
.cache/1688.db  SQLite（沿用旧库，新增 providers/proxy_channels/tasks/proxy_usage_events 四表）
```

## 启动

```bash
# 后端三件套（redis + celery + uvicorn:8765）
./start.sh

# 前端（开发模式）
cd web && npm run dev        # 默认 5173，可用 -- --port N 指定

# 停止后端
./stop.sh
```

日志在 `server/logs/`（uvicorn/celery/redis）。redis 如未安装：`brew install redis`。

## 功能页面

| 页面 | 说明 |
|---|---|
| Dashboard | 总店铺/待抓取/今日新增/运行任务/通道占用/近1小时速率 |
| 任务 | 手动创建 shop_crawl / contact_fetch 任务，多任务并行，进度条/速率/停止/人工确认 |
| IP 池 | 按厂商分组的通道状态：出口 IP、占用任务、近5分钟请求数、频率趋势、过期倒计时 |
| Worker | 在线 celery worker 看板：并发槽位、运行时长、正在执行的任务（可跳详情）；离线时醒目告警，新建任务也会提示。下方附 broker 任务队列（Redis celery list），可查看滞留消息并逐条清除（对应 pending 任务一并标记停止） |
| 厂商配置 | 密钥前端可配（config_schema 动态表单）、连通性测试、通道校准 |
| 数据 | 店铺/联系方式浏览筛选分页，导出 Excel/CSV |

## 首次真实采集建议

1. 前端「厂商配置」页对青果点「测试连通性」，确认密钥可用
2. 新建 shop_crawl 任务：`headed=true`、`proxy=true`、`yes=false`、小 target
3. 本机会弹出有头浏览器，人工过滑块/登录后，到任务页点「确认开始采集」
4. Cookie 按出口 IP 隔离自动写回；青果出口 IP 每 30 分钟轮换后需重新过一次验证（产品特性）
