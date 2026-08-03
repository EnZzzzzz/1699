# fetcher 分层设计文档

> 版本：v0.1 · P0+P1 阶段交付 · 2026-08-03
> 背景：将 `scraper/taobao_1688/`（common.py 1948 行单文件）与 `util/` 按面向对象方式重构为独立可安装包 `fetcher`。本阶段交付：包骨架、core 协议、网络层（P0），原子层、场景判断层、策略层、站点插件层骨架（P1）。控制循环、站点任务、CLI 属 P2+，不在本文档范围。

## 1. 分层总览

```
┌──────────────────────────────────────────────────────────┐
│ CLI 层（P2+）                                              │
├──────────────────────────────────────────────────────────┤
│ 控制层（P2+）  worker 循环：采集 → 判断场景 → 按策略表处置    │
├──────────────────────────────────────────────────────────┤
│ 站点插件层  sites/   SitePlugin 协议；alibaba1688 首个实现    │
├──────────────────────────────────────────────────────────┤
│ 策略层      strategy/  Policy（声明式策略表）+ Strategy      │
├──────────────────────────────────────────────────────────┤
│ 场景判断层  detect/    Detector 协议 + SceneInspector 优先级链 │
├──────────────────────────────────────────────────────────┤
│ 原子能力层  atoms/     Atom 协议：只做动作，报告 Outcome       │
├──────────────────────────────────────────────────────────┤
│ 网络层      net/       BrowserManager / IdentityStore / 代理  │
├──────────────────────────────────────────────────────────┤
│ 公共协议层  core/      Scenario / ActionResult / Session / ctx │
└──────────────────────────────────────────────────────────┘
```

核心循环（P2 实现，本阶段提供全部零件）：

```
数据采集(fetch) → 场景判断(SceneInspector → Scenario)
              → 策略表查询(Policy.decide → Strategy) → 执行处置 → 重新判断
              → 链用尽 GIVE_UP（放弃任务项）/ 熔断 ABORT（中止任务）
```

## 2. 两条铁律

1. **判断与行动分离**：`Detector` 只读页面/上下文状态返回 `Scenario`，绝不 goto/reload/点击；`Strategy` 与 `Atom` 只执行动作，绝不自己做场景检测。
2. **策略表是数据不是代码**：`Policy` 从 Python dict 加载（不用 YAML），条目为 `("策略名", 最大尝试次数)` 或终止条目 `("give_up", None)` / `("abort", None)`；支持站点级/任务级覆盖（`with_overrides` 按场景整条替换）。

## 3. core：公共协议

### Scenario（场景枚举，Detector 的唯一输出）

| 值 | 含义 | 判定来源 |
|---|---|---|
| `OK` | 页面正常 | 全部探测器未命中 |
| `EMPTY` | 页面加载了但内容为空（innerText < 30 字符） | 站点 EmptyPageDetector |
| `NET_STALL` | 网络卡、页面没加载出来（浏览器活着的 goto 超时等） | NetworkDetector |
| `NET_ERROR` | 代理隧道层错误（Chromium `net::ERR_*`，请求没到目标站） | NetworkDetector |
| `BROWSER_DEAD` | 浏览器进程死亡/会话被服务端关闭 | FatalErrorDetector |
| `RISK_SLIDER_PAGE` | 整页滑块跳转（URL/文本命中风控特征） | 站点 SliderPageDetector |
| `RISK_SLIDER_EMBED` | 内嵌滑块（与内容同屏，iframe/DOM 容器） | 站点 EmbeddedSliderDetector |
| `RISK_LOGIN` | 登录墙（跳 login.1688.com，最高级风控） | 站点 LoginWallDetector |
| `IP_ROTATED` | 出口 IP 已轮换（青果 30 分钟周期），Cookie 与出口错配 | 控制层经 CheckIPFresh 判定 |

### ActionResult / Outcome（Atom 与 Strategy 的返回）

`Outcome ∈ {OK, EMPTY, BLOCKED, NET_ERROR, FATAL, SKIPPED}`，对齐 docs/flow-architecture.md 的 AtomResult 契约，另加 `SKIPPED` 表示条件不满足未执行（如无头模式下的人工过证），策略层把 SKIPPED 当未解决继续推进链条——这正是无头模式登录墙自动落到「烧毁身份+换 IP」的机制。

### Session / WorkerContext / RunConfig

- `Session`：一次浏览器启动的产物（browser/page/identity/channel/req_proxies/seed_kit）。identity = 出口 IP（直连记 `"direct"`），是 Cookie 隔离与指纹固定的基准。
- `WorkerContext`：原子/探测器/策略共享的上下文（config/session/browser_manager/store/site/stop/log/last_error/state）。全部字段可空装配，单测可只给需要的部分。
- `RunConfig`：运行配置（headless/use_proxy/db_path/ip_retry/block_rest_min/max/max_consecutive_fail/seeds_dir 等），路径默认值全部解析到项目根 `.cache/`。

### 错误分级（core/errors.py，与旧版行为一致）

- `is_network_error`：`net::ERR_*` 特征（含兜底 `net::ERR`）——与风控无关，不计入风控连续失败计数；
- `is_fatal_browser_error`：`Target closed` / `has been closed` / `Target crashed` 等——必须重启浏览器；
- `browser_alive`：goto 超时后鉴别死浏览器 vs 页面挂起；
- `classify_error`：fatal → net_error → （浏览器死活探测）→ net_stall。

## 4. net：网络层（P0）

### BrowserManager（net/browser.py）

迁移 `launch_browser / relaunch_browser / warmup_cookies / save_cookies / check_ip_fresh / get_exit_ip / wait_for_license_seat / _fingerprint_args / _wait_manual_pass`。保留行为：

- **Cookie 按出口 IP 隔离**：库优先；仅直连模式用 cookie_json 种子兜底导入；代理模式新出口 IP 不播种（白板）或播独占种子身份（并记 `seed` IP 事件）；
- **warmup**：新 IP 访问首页让站点现场签发 Cookie 并立即回写；有头模式首页弹滑块先自动过证（auto_solve 回调），不过再等人工（每 5s 检测，期间每 90s 自动重试）；
- **GeoIP 超时放宽**：`CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS` setdefault 20s；
- **license 席位等待**：`PLAN_SEATS` 上限内轮询等残留租约释放；查询失败不阻塞；
- **launch watchdog**：240s 未返回打警告（纯观察线程，不跨线程触碰 playwright 对象）；
- **指纹按身份固定**：md5(identity/种子名) 取种（10000-99999），同 IP 重启指纹不变；不硬编码 UA；
- **relaunch**：先回写旧 Cookie 再关浏览器，线性退避 `min(30*attempt, 120)` 重试 `ip_retry` 次，失败抛 `BrowserLaunchError`；
- **check_ip_fresh**：出口 IP 查询失败短重试 3 次（间隔 5s）后判定隧道失效；IP 不一致判定已轮换。

与旧版的有意差异：`launch()` 失败从 `sys.exit` 改为抛 `BrowserLaunchError`（库不该替调用方退出进程）；风控检测通过 `block_check` 回调注入（站点插件提供），网络层不认识 1688。

### IdentityStore（net/identity.py）

包一层 ShopDB 的 Cookie 语义：`load / save / burn / info / save_from_context / seed_from_json`，外加 IP 事件透传（`record_event / stat_request / stat_block`）。域过滤（默认 `1688.com`）可配，为多站点预留。

### 代理（net/proxy/）

- `ProxyProvider` 协议 + `Channel` dataclass：`playwright_proxy()`（拆 server/username/password，内嵌账密 URL 直传 Chromium 会报 `ERR_NO_SUPPORTED_PROXIES`）与 `requests_proxies()`（查出口 IP 用）；
- `QingGuoProvider`：迁移 ChannelPool 全部行为（.cache 缓存 → /query → /get 补齐；轮询 acquire；30 分钟 TTL 与出口轮换周期对齐）；
- `KuaiDaiLiProvider`：单隧道产品，作厂商扩展示例；
- `DirectProvider`：直连 = 特殊通道（server=None）。

### 种子身份池（net/seeds.py）

- `load_seed_kits`：只保留设备绑定 Cookie；`SECURITY_COOKIE_NAMES`（x5sec/sgcookie/isg/登录态）绝不跨 IP 复制；`keep_x5sec` 实验组保留未过期 x5sec/x5secdata；不含 cna/cookie2 的种子判「不熟」跳过；
- `SeedBurnTracker`：种子在 ≥2 个新鲜 IP 上首请求秒拦（since ≤ 2）或触发登录墙 → 判定烧毁，停止播种退回白板（与旧引擎的 kit_burn_ips 逻辑一致）。

### ShopDB（db.py）

整体迁移，**schema 一字未改**（与 `.cache/1688.db` 兼容）。默认路径解析为项目根 `.cache/1688.db`，可用 `FETCHER_DB_PATH` 环境变量或构造参数覆盖。WAL + busy timeout 30s + `BEGIN IMMEDIATE` 原子认领等并发语义原样保留。

## 5. atoms：原子能力层（P1）

| 原子 | 迁移来源 | 说明 |
|---|---|---|
| `Sleep` | common.human_pause | 对数正态重尾分布（截断 [lo*0.5, hi*5]），min==max 退化为固定 |
| `BackoffSleep` | 引擎网络退避 | `min(base*attempt, cap)`，attempt 取 ctx.state |
| `Refresh` | flow-architecture 新增原子 | 网络卡顿轻处置；异常按 classify_error 分级 |
| `SolveSlider` | util/slider_track.py | 轨迹回放全套（多层滑块/点击重试/轨迹轮换/严格判定）；轨迹库为包内资源 `assets/tracks.json` |
| `RelaunchBrowser` | common.relaunch_browser | 成功后 ctx.session 指向新会话，`state["warm"]=True` 触发重新冷启动 |
| `SaveCookies` | common.save_cookies | 回写失败降级为日志不阻断（与旧版一致） |
| `CheckIPFresh` | common.check_ip_fresh | BLOCKED + `data["rotated"]` 供控制层走 IP_ROTATED |
| `ColdStart` | FetchTask.cold_start | 委托站点插件；无插件/异常均不阻断 |
| `ClearIdentity` | 引擎登录墙处理段 | 烧毁身份；`direct` 身份跳过（本机 Cookie 不烧毁） |
| `WaitHumanVerify` | common.wait_manual_unblock | 去 StatusBoard 依赖；保留「不干等」原则（auto_giveup 300s）与等待期自动重试 |
| `WaitHumanLogin` | common.wait_manual_login | Cookie 增量判定（登录态标记 / 新增 ≥3 个 Cookie 名） |

滑块回放只迁移「回放」能力（load_tracks/_densify/_raw_mouse/replay_track/solve_with_retry/solve_all_sliders/try_solve_slider）；录入与 CLI 测试工具仍留在 `util/slider_track.py`。

## 6. detect：场景判断层（P1）

`SceneInspector` 按优先级链询问：`FatalErrorDetector → NetworkDetector → 站点探测器（登录墙 → 整页滑块 → 内嵌滑块 → 空页）`，全部未命中返回 `OK`。

设计要点：

- **浏览器死活优先级最高**：浏览器死了，页面上的一切特征都不可信；
- **有异常时不读页面**：`ctx.last_error` 非空时站点探测器直接放行（页面状态是未加载完成的半成品，不可信），由 NetworkDetector 分级 NET_ERROR/NET_STALL；
- **登录墙先于滑块**：登录页常带"安全验证"文案，不先拆出来会被滑块场景截胡，而两者处置完全不同（登录墙要烧毁身份）；
- **内嵌滑块先于空页**：滑块与内容同屏时 innerText 正常，必须靠 iframe/DOM 特征识别，避免「误判为已通过」的老坑。

## 7. strategy：策略层（P1）

### 默认策略表

| 场景 | 策略链 | 对应旧行为 |
|---|---|---|
| NET_STALL | refresh×2 → swap_ip×3 → give_up | 新增轻处置（旧版无独立 NET_STALL 场景，按风控处理） |
| NET_ERROR | backoff_sleep×5 → swap_ip×2 → give_up | 旧引擎 `net_retry=5` 退避重试 + 代理模式重启浏览器 |
| BROWSER_DEAD | relaunch_browser×3 → **abort** | 旧引擎重启失败中止整个任务 |
| RISK_SLIDER_PAGE | solve_slider×3 → block_rest×1 → swap_ip×2 → give_up | 旧状态机：自动过证 → 原地休息 → 修复换 IP → 放弃 |
| RISK_SLIDER_EMBED | solve_slider×3 → wait_human_verify×1 → swap_ip×2 → give_up | 同上，人工等待档位对齐有头模式 |
| RISK_LOGIN | wait_human_login×1 → clear_identity_swap×2 → give_up | 有头等人工登录；无头 SKIPPED 直落烧毁身份+换 IP |
| IP_ROTATED | relaunch_browser×3 → abort | 旧引擎 IP 轮换重启浏览器 |
| EMPTY | refresh×2 → block_rest×1 → swap_ip×1 → give_up | 旧版空白按风控处理（软处置链） |

### Policy / AttemptTracker 语义

- `decide(scenario, tracker)`：熔断检查（`consecutive_fail >= max_consecutive_fail` → ABORT）→ 场景切换重置链 → 按声明顺序推进，次数用尽进下一条 → 终止条目/链尾 → GIVE_UP/ABORT；
- `tracker.note_success()`：任务项恢复，链状态与连续失败计数清零（`decide(OK)` 也会触发）；
- `tracker.note_failure()`：GIVE_UP 后由控制层调用，连续失败 +1（跨任务项累计，熔断语义与旧引擎 `--max-consecutive-fail` 一致）；
- 加载时校验：OK 场景不许配链；未注册的策略名直接 `KeyError`。

## 8. sites：站点插件层（P1）

`SitePlugin` 协议：`name / cookie_domain / homepage / detectors() / block_reason() / validate() / acquire_item() / fetch() / persist() / cold_start()`。`Alibaba1688Plugin` 为首个实现：

- 风控特征表与 4 个探测器在 `features.py`（含 `page_block_reason` 统一口径与 mtop 握手 `has_mtop_token / ensure_mtop_token`）；
- 任务钩子（acquire/fetch/persist/validate）留 P2（联系人/店铺/公司三个任务层各自实现或组合插件）。

## 9. 延迟导入约定

`cloakbrowser`（含 `cloakbrowser.license`）、`playwright`、`requests` 全部在方法体内导入：`import fetcher` 与跑单测不需要安装它们。`pyproject.toml` 中 playwright/requests 为声明依赖，cloakbrowser 为 optional extra（`pip install -e ".[cloak]"`）。

## 10. 测试

`tests/`（stdlib unittest，全 mock，不起真实浏览器/网络/数据库）：

- `test_detectors.py`：FakePage（url/innerText/frames/query_selector/连接状态）× 15 用例，覆盖全部 Scenario 分支与优先级竞争（登录墙 vs 滑块文案、异常 vs 站点特征、不可见选择器忽略）；
- `test_policy.py`：策略链推进顺序、attempt 计数、场景切换重置、GIVE_UP/ABORT 终止、熔断、覆盖合并、非法声明校验 × 15 用例；
- `test_identity.py`：临时 sqlite 上的隔离/过期剔除/UPSERT/burn/info/域过滤/IP 事件 × 10 用例。

运行：`cd fetcher && python -m unittest discover -s tests`（装了 pytest 也可 `python -m pytest tests -x -q`）。

---

# P2+P3 增补：控制层 / 任务实现 / Engine / CLI

> v0.2 · 2026-08-03 · 在 P0+P1 零件之上装配完整采集能力

## 11. 控制层（fetcher/control/）

### 11.1 CrawlLoop（loop.py）— 单 worker 核心循环

```
run():
    启动浏览器（ip_retry 次退避重试，watchdog/席位/warmup 在 BrowserManager 内）
    warm = True（ctx.state["warm"]，换 IP 后由 RelaunchBrowser 原子重新置位）
    while not stopped:
        批次配额：done_in_batch >= batch_num → 收工(max_batches) / 大休息(±10% 抖动)
        冷启动（cold_start_before_acquire 的任务在 acquire 前执行）
        item = task.acquire_item(ctx)；无任务 → 退出
        代理模式：check_ip_fresh → 已轮换则重启浏览器重绑 Cookie
        冷启动（其余任务在 acquire 后执行）
        kind, count = _process_item(item)          # 见 11.2
        成功后回写 Cookie（意外退出不丢信任链）
        task.after_item(ctx, item)
        ip_request_budget 检查 → 采满预算主动换 IP（budget_stuck 放行）
        --limit 到顶收工
        样本间隔（sample_min/max + wid 递增错峰）
        rest_every 周期随机长休息
    finally: 回写 Cookie → 关浏览器 → 关 DB（worker 所有权）
```

### 11.2 _process_item — item 级重试循环（策略表驱动）

```
while not stopped:
    ctx.last_error = None
    result = task.fetch(ctx, item)
    scenario = inspector.inspect(ctx)
    if scenario is OK:                              # 兜底映射（信 fetch 自报）
        result is None      → RISK_SLIDER_PAGE      # 旧 scrape None 语义
        outcome BLOCKED     → RISK_SLIDER_PAGE      # 如 mtop 令牌缺失
        outcome NET_ERROR   → NET_ERROR
        outcome FATAL       → BROWSER_DEAD
        outcome OK 但 validate 结构化校验失败 → EMPTY
    tmd 簿记：按 identity 计请求数（NET_ERROR/BROWSER_DEAD 不计）
    if scenario is OK: circuit/tracker 清零 → on_success → return
    风控簿记：record_ip_event + ip_stat_block + since 清零
             + 登录墙判定当下烧毁身份 Cookie + 种子烧毁判定
    熔断：CIRCUIT_SCENARIOS（风控三兄弟 + EMPTY + NET_STALL）计数，
          到顶 on_abort + stop.set() → return abort
    decision = policy.decide(scenario, tracker)
    ABORT   → on_abort + stop.set()
    GIVE_UP → on_giveup(kind=net/block) + giveup_cost
    CONTINUE → strategies[decision.strategy].run(ctx) → 重试同一 item
```

### 11.3 CircuitBreaker（circuit.py）

worker 级连续失败熔断，与旧引擎同点位（场景判定当下立即计数判断）。
`CIRCUIT_SCENARIOS = {RISK_SLIDER_PAGE, RISK_SLIDER_EMBED, RISK_LOGIN,
EMPTY, NET_STALL}` —— NET_STALL 计入是刻意对齐旧版「goto 超时返回
None 按风控计」的语义；NET_ERROR / BROWSER_DEAD / IP_ROTATED 与
风控无关不计数。

### 11.4 NET_STALL → NET_ERROR 经验规则（显式说明）

P1 报告提过：部分代理故障表现为超时（NET_STALL）而非 `net::ERR_*`
（NET_ERROR），探测时无法可靠区分。落实为策略表结构而非代码分支：
NET_STALL 链 `refresh×2 → swap_ip×3 → give_up` —— 前 2 次按「页面
没加载出来」轻处置，刷新无效后进入与 NET_ERROR 相同的重处置
（换 IP）。即「连续刷新无效视同 NET_ERROR」由声明式链条自然表达，
两处共用 swap_ip 策略，无重复逻辑。

### 11.5 StatusBoard（board.py）

旧 StatusBoard 原样迁移（固定 workers 行 + 滚动日志 + CJK 宽度折行）。
库与展示解耦：CrawlLoop 只调 ctx.set_status / ctx.log，board 是可选
listener；无 board 时状态 noop、日志 print。

## 12. 任务实现（sites/alibaba1688/）

| 任务 | 文件 | 迁移来源 | 要点 |
|---|---|---|---|
| contact | contact.py | contact_fetcher.py | claim_pending_shops 原子认领；结构化 validate（字段/标签判空，「无联系方式」合法页不误判）；done/no_contact/failed 语义不变 |
| shop | shop.py | shop_crawler.py | CategoryPool 互斥；mtop 无令牌 fetch 自报 BLOCKED 不碰搜索；exhausted/页码不前进；批次配额按店铺数 |
| company | company.py | company_crawler.py | KeywordPool；"company:" 前缀进度隔离；charset=utf8 必带 |

有意差异（三任务一致）：fetch 内不再就地自动过证（旧版 scrape 里
solve_all_sliders），统一由 SolveSlider 策略处置 —— 判断与行动分离，
行为等价（策略链 RISK_SLIDER_* 首档即 solve_slider×3）。

## 13. Engine（control/engine.py）与 CLI

Engine 迁移 run_workers：一 worker 一通道轮询分配、种子独占认领
（含 --seed-x5sec A/B）、StatusBoard 装配、SIGTERM/SIGHUP 优雅退出、
stagger 错开启动、KeyboardInterrupt 收尾、summary 汇总。每 worker
独立 ShopDB/BrowserManager/ctx/CrawlLoop（工厂可注入，测试友好）。

CLI（`python -m fetcher` / console_scripts `fetcher`）只做装配：

```bash
python -m fetcher 1688 contact --proxy --headed -n 100 --max-batches 4
python -m fetcher 1688 shop --proxy -n 500 --max-batches 2
python -m fetcher 1688 company --proxy --limit 300
python -m fetcher 1688 contact --tmd-report      # 只出报表不采集
```

共享参数全量迁移自 add_common_args（batch-rest/ip-retry/block-rest/
net-retry/max-consecutive-fail/headed/rest-every/sample/rest/stagger/
proxy/seeds/seed-x5sec/channels/workers），新增 --limit（每 worker
总量上限）、--db（库路径）、--no-auto-solve（关自动过证）。
策略表可被 CLI 参数影响：--max-consecutive-fail 同时作用于
CircuitBreaker 与 Policy；任务级/站点级覆盖用 Policy.with_overrides。

## 14. 已知边界（P4 候选）

- SwapIPStrategy 的「等轮换再重启」在无头模式 sleep block_rest
  （默认 10~15 分钟）期间不做任何事 —— 与旧引擎一致，但可考虑
  在此期间先服务其他任务项（需要 item 级调度，超出当前设计）。
- CategoryPool/KeywordPool 是进程内内存池，多进程部署时类目占用
  互斥失效（旧版同限制；服务化阶段再解）。
- 状态板 detail 路由规则（[X]/[!]/[license] 进滚动日志）沿自旧版
  字符串匹配，后续可换结构化 severity。

---

# P4 增补：站点扩展性验证（taobao 插件 + 注册机制）

> v0.3 · 2026-08-03 · 目标：证明「加一个新站点只动 sites/ 目录，四层主框架一行不改」

## 15. 插件注册机制

`sites/__init__.py` 提供轻量注册表：

- `register_site(name, PluginCls)`：各站点子包 `__init__.py` 末尾自注册；
- `_autodiscover()`：`pkgutil` 扫描 `sites/` 全部子目录并 import（导入即注册），新增目录无需登记到任何清单；
- `get_site(name)` / `site_names()`：CLI/Engine 的唯一取件入口。

CLI（`build_parser`）的站点/任务子命令全部由注册表驱动生成；策略表的站点级覆盖经 `site.policy_overrides` + `Policy.with_overrides` 在装配层应用。框架四层（net/atoms/detect/strategy）与控制层零站点硬编码。

## 16. 如何新增一个站点插件（checklist）

以 `mysite` 为例：

- [ ] **建目录** `fetcher/sites/mysite/`，含 `__init__.py` + `features.py` + 任务文件
- [ ] **特征表**（`features.py`）：`HOMEPAGE / SEARCH_HOME / LOGIN_URL_PATTERNS / BLOCK_URL_PATTERNS / BLOCK_TEXT_KEYWORDS / EMBEDDED_SLIDER_* / COOKIE_DOMAIN`；阿里系站点直接用 `detect.generic` 的参数化探测器 + `make_block_reason` 装配，只写数据不写判定逻辑
- [ ] **探测器**：`make_detectors()` 按「登录墙 → 整页滑块 → 内嵌滑块 → 空页」优先级返回实例列表；非阿里系站点可自写 Detector（协议：`detect(ctx) -> Scenario | None`，只读不动浏览器）
- [ ] **mtop/握手**（如适用）：`sites/mtop.py` 传 domain 复用；其他机制在站点目录内自实现
- [ ] **插件类**：`name / cookie_domain / homepage / detectors() / block_reason() / task_names() / make_task() / cold_start()`；可选 `policy_overrides`（站点级策略覆盖）
- [ ] **任务**：继承 `control.Task`，实现 `acquire_item / fetch / validate / on_success(+on_giveup/giveup_cost/after_item)`；fetch 异常必须写 `ctx.last_error` 并按 `classify_error` 分级；validate 用结构化字段判空（探测器文本阈值只是兜底）
- [ ] **存储隔离**：不复用其他站点的表；新表放自己的 db 文件或带站点前缀，或像 taobao 一样落 JSONL
- [ ] **自注册**：子包 `__init__.py` 末尾 `register_site("mysite", MySitePlugin)`
- [ ] **测试**（仿 `tests/test_plugin_extension.py`）：
  - 探测器单测：登录墙/滑块/空页场景 + 与已有站点的域隔离互测
  - 解析器/validate 单测（纯函数 + mock page.evaluate）
  - fetch 门控单测（如 mtop 无令牌必须 BLOCKED 且不触碰目标端点）
  - 全流程：mock session + CrawlLoop 跑通（证明不改框架）
- [ ] **CLI 验证**：`python -m fetcher mysite <task> --help` 自动生成

## 17. taobao 插件与「待真实环境校准」清单

taobao 与 1688 判定结构 100% 复用（参数化探测器 + make_block_reason + sites/mtop.py），差异只有：特征表数据、search 任务（内存关键词队列 + JSONL 落盘）、policy_overrides（滑块处置加码）。

**[CAL] 待校准条目**（真实环境首跑时逐条核对）：
- [CAL-1] LOGIN_URL_PATTERNS：login.taobao.com；天猫 login.tmall.com 未含
- [CAL-2] BLOCK_URL_PATTERNS：sec.taobao.com/punish/x5sec/captcha；"_____tmd_____" 是否出现在整页跳转 URL
- [CAL-3] BLOCK_TEXT_KEYWORDS：与 1688 相同，淘宝是否有差异文案
- [CAL-4] EMBEDDED_SLIDER_SELECTORS：nocaptcha/nc_*/baxia 在淘宝搜索页的挂载方式
- [CAL-5] mtop 握手落地页 s.taobao.com 是否足够低敏
- [CAL-6] 内嵌数据路径 __INIT_DATA__/g_page_config + mods.itemlist 两种结构兼容是否覆盖现行页面
- [CAL-7] DOM 兜底选择器 .item/.title/.price/.shop（淘宝改版频繁，大概率需重录）
- [CAL-8] 「无结果」关键词（没有找到/找不到相关/没有相关宝贝）
- taobao 的 ip_request_budget=12 沿用 1688 经验值，待淘宝实测配额墙
