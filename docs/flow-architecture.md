# 原子能力 + DAG 流水线架构设计

> 版本：v1 · 2026-08-01 · 设计基准文档（与 owner 逐条确认后的结论）
> 状态：v1 原子层已按 §3 落地；flows 表 DAG 编排（§4~§8）**未落地**，且已被
> docs/scheduler-architecture.md 的「work_items 队列 + 消费者池 + daemon 调度」路线取代；
> §2/§6/§7 相关段落为历史设计，仅存档参考。2026-08-08（P5）已删除 flows 表与
> tasks.flow_id 列（表重建迁移）。
> 关联文档：docs/service-architecture.md（服务化总体架构，本文档是其演进）

## 1. 需求确认结论

| 议题 | 结论 |
|---|---|
| 核心目标 | 任务逻辑从"写死在 Python 控制流"升级为"原子能力（Atom）+ 编排层（DAG）"，流水线可保存、可复用、可视化 |
| 颗粒度 | 两级：编排 DAG 为粗粒度（单任务 5~15 节点）；重试/换 IP/熔断等控制流是**节点策略配置**，不画成 DAG 的边 |
| 循环表达 | 容器节点（如 `for_each_shop` 带子图），DAG 保持无环，不画回边 |
| 并发表达 | 容器节点的 `parallel: N` 属性，引擎负责起 N 个执行上下文并管理共享配额；不在图中画并行分支 |
| worker 可观测 | 并行容器节点可下钻，能看到每个 worker 独立的执行轨迹、当前所在子节点、各自进度 |
| 节点实时进度 | 每种节点实时上报运行时状态（elapsed / 自定义进度字段），前端看板画进度条/环形图；Sleep 要能看到已睡多久 |
| 资源生命周期 | 引擎统一管理：DAG 声明资源（通道/浏览器），入口 acquire、出口 release（含异常兜底）；原子经 `ctx` 取用；SwapIP 换通道必须经引擎接口报备 |
| 流水线保存 | `flows` 表存「DAG 结构 + 全部节点参数」为模板（重试策略、是否换 IP、sleep 时长与浮动区间等）；执行时选模板 + 补少量运行时变量一键运行；模板可复制出新版本 |
| 前端分期 | v1 只读流程图 + 实时节点状态看板（非静态图，轮询/SSE 刷新）；v2 可视化拖拽编辑器 |
| 迁移策略 | 不动现有 `shop_crawl` / `contact_fetch`；新增独立 `flow` 任务类型；内置模板 1:1 复刻现有两任务行为，灰度验证等价后逐步替代、最终下线旧实现 |

## 2. 分层架构（现状）

```
┌────────────────────────────────────────────────────┐
│ 调度层  fetcher daemon：QueueRouter 多队列调度       │  ← 现状
│         消费者池（work_items 队列 + 跨站冷却填充，   │
│         见 scheduler-architecture.md）               │
├────────────────────────────────────────────────────┤
│ 引擎层  Engine + CrawlLoop / LocalLoop               │  ← 现状
│         逐工作项执行（认领→IP 保鲜→fetch→簿记）      │
├────────────────────────────────────────────────────┤
│ 原子层  Atom Registry（能力目录，标准契约）          │  ← 现状（§3 已落地）
│         sleep / swap_ip / fetch_contact / ...       │
├────────────────────────────────────────────────────┤
│ 资源层  通道池 · BrowserManager · ShopDB             │  ← 现状
│         事件/进度落 SQLite（task_events/progress_json）│
└────────────────────────────────────────────────────┘
```

关键决策说明：

- **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由策略层统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在策略层一处，流水线保持干净。（现状一致，保留）
- **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在策略层。这使原子可独立测试。（现状一致，保留）
- **任务执行**：任务由 daemon 的消费者执行（Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列 + 消费者池（见 scheduler-architecture.md §8），无 Celery。
- **事件与进度**：事件/进度写 SQLite（task_events / progress_json），无 Redis 心跳；协作式停止走 stop_requested 与循环 Timer（平台 runner）。

## 3. 原子（Atom）契约与清单

### 3.1 契约

```python
class Atom:
    name: str                    # 注册名，如 "swap_ip"
    title: str                   # 显示名，如 "更换出口 IP"
    inputs: dict                 # 需要的 ctx 键，如 {"channel": "Channel"}
    outputs: dict                # 写回的 ctx 键
    param_spec: dict             # JSON Schema，前端表单/校验用
    def run(self, ctx: Context, params: dict) -> AtomResult: ...

@dataclass
class AtomResult:
    outcome: str                 # "ok" | "blocked" | "net_error" | "empty" | ...
    detail: str = ""             # 原因描述（事件消息用）
    data: dict = field(default_factory=dict)  # 产出数据（如抓取结果）
```

- 原子执行期间可随时调 `ctx.report_progress({...})` 上报节点实时进度（Sleep 报 `{total, elapsed}`；fetch 报 `{retry, exit_ip}`）。
- 原子**不直接**操作通道池和浏览器生命周期，一律经 `ctx.resources`（引擎代理）访问。

### 3.2 首期原子清单（从现有代码抽取，行为不变）

| name | 显示名 | 来源（现有代码） | 主要参数 |
|---|---|---|---|
| `sleep` | 等待 | `start_delay_countdown` / `human_pause` | `min`, `max`（相等=固定），实时报 elapsed |
| `acquire_channel` | 申请通道 | `PoolClient.acquire` | `n`, `proxy` |
| `launch_browser` | 启动浏览器 | `browser.launch_browser` | `headed` |
| `ensure_fresh_ip` | 出口 IP 保鲜检查 | `_check_ip_fresh` + 换通道重启 | 内部调 `swap_ip` |
| `swap_ip` | 更换出口 IP | `swap_channel_with_events` + `_relaunch_browser` | `ip_retry` |
| `human_pause` | 拟人停顿 | `pg.human_pause` | `min`, `max` |
| `claim_shops` | 认领店铺 | `db.claim_pending_shops` | `n` |
| `fetch_contact` | 抓取联系方式 | `pg.scrape_contact` + 入库/标记 | — |
| `crawl_category` | 采集店铺分页 | shop_crawl 单轮采集逻辑 | `delay_min/max` |
| `confirm_human` | 人工确认 | `wait_confirmation` | `timeout` |
| `for_each_shop` | 店铺循环（容器） | contact_fetch 主循环 | `num`, `batch_rest`, `max_batches`, `limit`, `parallel` |

> 容器节点是特殊 Atom：`body` 为子 DAG，引擎对其每个迭代执行子图。

后续新增（v1.1，2026-08-02，滑块自愈能力接入）：

| name | 显示名 | 来源 | 主要参数 |
|---|---|---|---|
| `refresh_page` | 刷新页面 | 新增（网络卡顿轻处置） | `timeout_ms`, `render_wait` |
| `solve_slider` | 过滑块验证 | 包装 `util/slider_track.py`（轨迹库回放/多层滑块） | `max_attempts`, `max_rounds` |
| `slider_repair` | 风控修复（滑块优先） | 新增组合原子：滑块 → 等待数分钟+刷新 → 再过滑块 → 换 IP（按 `_attempt` 分阶段） | `slider_attempts`, `wait_min/max`, `ip_retry` |
| `net_repair` | 网络修复（先刷新后换 IP） | 新增组合原子：刷新 → 换 IP（按 `_attempt` 分阶段） | `refresh_attempts`, `ip_retry` |

配套内置模板「联系人提取·滑块自愈」：fetch 节点 `on_blocked: {do: slider_repair, retry: 5}`、
`on_net_error: {do: net_repair, retry: 5}`、熔断放宽到连续 6 次。

## 4. DAG 定义（flows.dag_json）

```jsonc
{
  "version": 1,
  "resources": ["channel", "browser"],   // 引擎统一 acquire/release
  "run_inputs": {                        // 运行时变量（执行时补，不进模板）
    "limit": {"type": "int", "default": 0, "label": "本次最多抓取"}
  },
  "nodes": [
    {"id": "start_delay", "atom": "sleep",
     "params": {"min": 0, "max": 0}},
    {"id": "acquire", "atom": "acquire_channel",
     "params": {"n": 1, "proxy": true}},
    {"id": "browser", "atom": "launch_browser",
     "params": {"headed": false}},
    {"id": "loop", "atom": "for_each_shop",
     "params": {"num": 10, "batch_rest": 900, "max_batches": 0,
                "rest_every": 20, "rest_min": 60, "rest_max": 180,
                "rotate_every": 0, "parallel": 1},
     "body": [
       {"id": "check_ip", "atom": "ensure_fresh_ip"},
       {"id": "fetch", "atom": "fetch_contact",
        "on_blocked":   {"do": "swap_ip", "retry": 2},
        "on_net_error": {"do": "swap_ip", "retry": 5},
        "circuit_breaker": {"consecutive_fail": 5, "action": "abort_task"}},
       {"id": "pause", "atom": "human_pause", "params": {"min": 3, "max": 7}}
     ]}
  ],
  "edges": [                              // 顶层节点间的顺序依赖（可选；缺省按数组序）
    ["start_delay", "acquire"], ["acquire", "browser"], ["browser", "loop"]
  ]
}
```

约束：

- `nodes` 数组内顺序即缺省执行序；`edges` 仅用于表达非线性依赖（v1 线性即可，字段预留）。
- 策略键：`on_blocked` / `on_net_error` / `on_<outcome>`，值 `{"do": "<atom>", "retry": N}`；`circuit_breaker` 为节点级熔断。
- 校验：加载时做 Schema 校验 + 原子存在性 + 参数校验 + 容器 body 递归校验 + 无环检查。

## 5. FlowExecutor 设计

### 5.1 执行模型

```
run_flow(task_id)                       # Celery 入口
  ├─ 加载 task → flow 模板 + run_inputs → 校验 DAG
  ├─ 声明资源入池（acquire 通道 / launch 浏览器挂到 ResourceManager）
  ├─ 拓扑遍历顶层节点：
  │    普通节点  → 策略拦截器包一层 → atom.run(ctx, params)
  │    容器节点  → 按 parallel 起 N 个 worker 上下文，
  │                 各自循环执行 body 子图，共享配额锁（沿用现有 state/lock 语义）
  ├─ 每个节点包 try/finally：节点状态/事件/进度上报
  └─ 出口：ResourceManager 全量 release（含异常兜底）→ 写回 Cookie → 关浏览器
```

### 5.2 策略拦截器（引擎核心）

```python
def run_with_policy(node, ctx):
    attempts = {}
    while True:
        result = atom.run(ctx, node.params)
        if result.outcome == "ok":
            return result
        policy = node.policies.get(f"on_{result.outcome}")
        cb = node.circuit_breaker
        if cb and ctx.consecutive_fail >= cb["consecutive_fail"]:
            abort_task()                      # 熔断：中止整个任务
        if policy and attempts.get(result.outcome, 0) < policy["retry"]:
            attempts[result.outcome] = attempts.get(result.outcome, 0) + 1
            run_atom(policy["do"], ctx)        # 如 swap_ip
            continue
        return result                          # 策略用尽，交还调用方（容器决定标记 failed）
```

### 5.3 上下文（ctx）

```python
ctx.task_id / ctx.rt          # TaskRuntime（事件/进度/心跳/停止）
ctx.resources                 # 引擎资源代理：channel / browser / page / pool_client
ctx.vars                      # 节点间数据传递（黑board），如 claim_shops 产出的店铺
ctx.worker_id                 # 并行容器内 worker 序号（顶层为 None）
ctx.consecutive_fail          # 熔断计数（worker 级）
ctx.report_progress(dict)     # 节点实时进度上报
ctx.stop_requested()          # 协作式停止检查
```

### 5.4 节点级状态上报

- 每个节点（含 worker 实例维度）维护运行时状态：`pending / running / ok / failed / skipped / aborted`，`started_at / finished_at / elapsed`，以及原子自定义的 `progress` 字段。
- 落点：任务 `progress_json` 增加 `nodes: {node_key: {...}}`（node_key = `节点id` 或 `节点id#w0`），与现有任务级字段共存；`task_events.data_json` 统一带 `node_id` / `worker_id`。
- 前端轮询/SSE 取 `progress_json.nodes` 渲染看板，无需新增推送通道。

## 6. 存储设计（新增 1 张表 + tasks 表加列）

> ⚠️ 本节为历史设计：flows 表与 tasks.flow_id 从未承载生产语义，P5（2026-08-08）
> 已通过幂等表重建删除 flows 表与 flow_id 列。SQL 仅为存档。

```sql
-- 流水线模板（DAG + 节点参数整体保存，可复制出新版本）
CREATE TABLE flows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,            -- 如 "联系人提取·标准"
    description TEXT,
    dag_json    TEXT NOT NULL,            -- §4 定义
    builtin     INTEGER NOT NULL DEFAULT 0,  -- 1=内置复刻模板（只读防误改）
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- tasks 表加列（ALTER TABLE，不动现有行）
ALTER TABLE tasks ADD COLUMN flow_id INTEGER REFERENCES flows(id);
-- type 新增取值 "flow"；params_json 存 run_inputs 实参（如 {"limit": 100}）
```

- 任务创建（type=flow）：`{flow_id, run_inputs}` → 快照 `dag_json` 进任务（防止模板后改影响历史任务的可追溯；快照存于 params_json._dag_snapshot）。
- 节点运行状态不落新表，走 `progress_json.nodes`（易过期、易重写，符合"看板"语义）；需要审计的细节已在 `task_events`。

## 7. API 设计（新增）

> 本节 flows/atoms 端点为历史设计，未实现；任务 API 现仅 tasks 通用端点。

```
GET    /api/flows                 # 模板列表（未落地）
POST   /api/flows                 # 新建模板（含 DAG 校验）（未落地）
GET    /api/flows/{id}            # 模板详情（未落地）
PUT    /api/flows/{id}            # 更新（builtin=1 拒绝）（未落地）
POST   /api/flows/{id}/duplicate  # 复制出新版本（未落地）
DELETE /api/flows/{id}            # 删除（被任务引用时仅标记 archived）（未落地）
GET    /api/atoms                 # 原子目录（name/title/param_spec），前端表单/编辑器用（未落地）
POST   /api/flows/validate        # 独立 DAG 校验（保存前调用）（未落地）
POST   /api/tasks                 # 通用任务创建；type=flow 时传 {flow_id, run_inputs}（flow 分支未落地）
```

任务进度接口 `GET /api/tasks/{id}` 的响应中 `progress.nodes` 即节点看板数据，结构：

```jsonc
{
  "collected": 42, "pending": 300, "per_minute": 3.1,
  "nodes": {
    "start_delay": {"status": "ok", "elapsed": 12.0},
    "loop":        {"status": "running", "batch": 2, "parallel": 2},
    "loop/fetch#w0": {"status": "running", "progress": {"retry": 1, "exit_ip": "1.2.3.4"}},
    "loop/pause#w1": {"status": "running", "progress": {"total": 7, "elapsed": 3.2}}
  }
}
```

## 8. 前端设计（v1：只读图 + 实时看板）

- **流水线页**：模板列表（名称/描述/更新时间）+「从模板运行」按钮（弹 run_inputs 表单）。
- **模板详情 / 任务详情**：React Flow 渲染 DAG（只读，锁定拖拽）。容器节点显示为分组框，body 子图嵌套内层；`parallel > 1` 的容器节点带 "×N" 徽标，点击下钻查看每个 worker 实例的执行轨迹（当前子节点高亮 + 各自进度）。
- **节点状态视觉**：颜色 = status（灰 pending / 蓝 running 呼吸 / 绿 ok / 红 failed）；running 节点卡片内嵌进度组件——Sleep 类显示环形/条形进度（elapsed/total），fetch 类显示重试计数与当前出口 IP。
- **刷新**：复用现有 WebSocket 聚合推送（progress_json 变更即推），断线降级 2s 轮询。
- **v2 预留**：同一 React Flow 画布切换 editable，节点拖拽 + 参数侧栏表单（param_spec 驱动）+ 保存前调 `/api/flows/validate`。

## 9. 落地路线

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 原子抽取 | Atom 契约 + Registry；从两个现有 worker 抽出 §3.2 清单原子（只改组织形式，不改行为） | 原子单测可独立跑通 |
| P1 引擎 | FlowExecutor（拓扑/容器/并行/策略拦截/资源管理/节点状态上报）+ flows 表 + `run_flow` + §7 API | 单元级 DAG 可执行 |
| P2 内置模板 | 内置 2 个模板 1:1 复刻 `shop_crawl` / `contact_fetch`；灰度跑通，对比旧任务行为等价（事件序列、抓取结果口径） | 同参数下产出一致 |
| P3 前端看板 | 流水线页 + 只读 DAG 图 + 节点实时看板 + worker 下钻 | 看板实时反映执行 |
| P4 替代 | 新任务默认走 flow；旧类型冻结（不再加功能），稳定一个周期后下线旧实现 | 旧代码路径删除 |
| P5 编辑器（v2） | 可视化拖拽编辑 + 保存/校验 | 前端可新建模板 |

## 10. 明确的非目标（v1 不做）

- 跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度已由 daemon 实现（scheduler-architecture.md §8）
- 任意条件分支图（if/else 边）；条件能力由策略配置覆盖
- 模板版本 diff / 回滚（仅支持复制出新模板）
- 多用户/权限（沿用单机无鉴权前提）
