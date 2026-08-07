# fetcher

1688 采集项目的面向对象重构包（P0+P1 阶段）：网络层 / 原子能力层 / 场景判断层 / 策略层 / 站点插件层。旧实现（`scraper/`、`util/`）保持不动，本包独立可安装。

## 分层

| 层 | 模块 | 职责 |
|---|---|---|
| 公共协议 | `fetcher/core/` | Scenario 枚举、ActionResult、Session、WorkerContext、错误分级 |
| 网络层 | `fetcher/net/` | BrowserManager（启动/预热/重启/席位/watchdog/指纹）、IdentityStore（Cookie 按出口 IP 隔离）、代理（青果/快代理/直连）、种子身份池 |
| 原子层 | `fetcher/atoms/` | Sleep / Refresh / SolveSlider / RelaunchBrowser / SaveCookies / CheckIPFresh / ColdStart / ClearIdentity / WaitHuman* |
| 判断层 | `fetcher/detect/` | Detector 协议 + SceneInspector 优先级链（只读状态，绝不动浏览器） |
| 策略层 | `fetcher/strategy/` | Policy（声明式策略表，dict 加载可覆盖）+ AttemptTracker + 策略实现 |
| 站点插件 | `fetcher/sites/` | SitePlugin 协议；`alibaba1688` 首个实现（风控特征表/探测器/mtop 握手） |
| 存储 | `fetcher/db.py` | ShopDB（schema 与 `.cache/1688.db` 完全兼容） |

设计细节见 [docs/design.md](docs/design.md)。

## 安装

```bash
pip install -e .          # 声明依赖：playwright、requests
pip install -e ".[cloak]" # 另装 cloakbrowser（运行采集所需）
```

重依赖（cloakbrowser / playwright / requests）全部延迟导入：`import fetcher` 与跑单测不需要安装它们。

## 快速上手

```bash
# CLI（console_scripts: fetcher；或 python -m fetcher）
python -m fetcher 1688 contact --proxy --headed -n 100 --max-batches 4
python -m fetcher 1688 shop --proxy -n 500 --max-batches 2
python -m fetcher 1688 company --proxy --limit 300
python -m fetcher 1688 contact --tmd-report     # 只出 tmd 报表
python -m fetcher taobao search --proxy -n 30   # 第二个站点：淘宝商品搜索
python -m fetcher daemon --proxy                # 常驻模式：1688 contact 从 work_items 队列持续消费
# 站点/任务子命令由 sites 注册表自动发现生成，加目录即接入
```

`daemon` 子命令 = 1688 contact 常驻模式：消费者从 `work_items` 表认领工作项，
shops 表 pending 行自动补货入队，队列取空后挂起等货而非退出。支持全部共享
网络层参数（`--proxy` / `--workers` / `--headed` 等，同各任务子命令），另有
`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
每个 worker 跑完 N 个后退出，作冒烟/联调的收工手段。
**daemon 与旧 CLI `1688 contact` 同站互斥**：两边启动都会把 shops 的
in_progress 重置为 pending（daemon 另回收 work_items 的 claimed 残留），
同站同跑会互相重置，同一时刻只跑一个。

```python
# 库用法（CLI 即以下装配的薄壳）
from fetcher import RunConfig, Alibaba1688Plugin, Policy
from fetcher.net.proxy import QingGuoProvider
from fetcher.control import Engine

cfg = RunConfig(use_proxy=True, headless=False, batch_num=100)
site = Alibaba1688Plugin()
task = site.make_task("contact")          # contact / shop / company
task.prepare(cfg)
engine = Engine(cfg, task, site=site,
                provider=QingGuoProvider(),
                policy=Policy(max_consecutive_fail=cfg.max_consecutive_fail))
engine.run()
```

## 测试

```bash
cd fetcher
python -m unittest discover -s tests     # stdlib，无需安装任何东西
# 或（若装了 pytest）
python -m pytest tests -x -q
```

全部 mock：不起真实浏览器、不发真实网络请求、不碰真实数据库（临时 sqlite）。
当前 85 个用例：Detector / Policy / IdentityStore（P0+P1）+ CrawlLoop
集成 + contact 任务 + Engine 编排（P2+P3）+ 站点扩展性（P4：第三方
最小站点注册并跑通 CrawlLoop、taobao 探测器域隔离、解析器/validate/
fetch 门控、策略覆盖）。

## 本阶段边界

P2+P3 已交付控制层与 CLI。遗留：多进程类目池互斥、换 IP 等待期的
item 级调度（见 docs/design.md §14）。
