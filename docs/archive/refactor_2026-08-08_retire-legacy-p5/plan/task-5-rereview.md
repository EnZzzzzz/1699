# Re-review package — Step 4.1 fix round 1 (Fix base c9b7cf17833857cfd955d1f006c500cd1fb47306..HEAD)

## git log
2b10892 docs(flow-architecture): 修正 scheduler-architecture 引用 §8 → §3/§5（队列+消费者池调度实际在 §3 分层架构 / §5 调度循环）

## git diff --stat
 docs/flow-architecture.md | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

## git diff -U10
diff --git a/docs/flow-architecture.md b/docs/flow-architecture.md
index 76bc8a9..eacc9f4 100644
--- a/docs/flow-architecture.md
+++ b/docs/flow-architecture.md
@@ -38,21 +38,21 @@
 ├────────────────────────────────────────────────────┤
 │ 资源层  通道池 · BrowserManager · ShopDB             │  ← 现状
 │         事件/进度落 SQLite（task_events/progress_json）│
 └────────────────────────────────────────────────────┘
 ```
 
 关键决策说明：
 
 - **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由策略层统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在策略层一处，流水线保持干净。（现状一致，保留）
 - **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在策略层。这使原子可独立测试。（现状一致，保留）
-- **任务执行**：任务由 daemon 的消费者执行（Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列 + 消费者池（见 scheduler-architecture.md §8），无 Celery。
+- **任务执行**：任务由 daemon 的消费者执行（Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列 + 消费者池（见 scheduler-architecture.md §3/§5），无 Celery。
 - **事件与进度**：事件/进度写 SQLite（task_events / progress_json），无 Redis 心跳；协作式停止走 stop_requested 与循环 Timer（平台 runner）。
 
 ## 3. 原子（Atom）契约与清单
 
 ### 3.1 契约
 
 ```python
 class Atom:
     name: str                    # 注册名，如 "swap_ip"
     title: str                   # 显示名，如 "更换出口 IP"
@@ -265,14 +265,14 @@ POST   /api/tasks                 # 通用任务创建；type=flow 时传 {flow_
 |---|---|---|
 | P0 原子抽取 | Atom 契约 + Registry；从两个现有 worker 抽出 §3.2 清单原子（只改组织形式，不改行为） | 原子单测可独立跑通 |
 | P1 引擎 | FlowExecutor（拓扑/容器/并行/策略拦截/资源管理/节点状态上报）+ flows 表 + `run_flow` + §7 API | 单元级 DAG 可执行 |
 | P2 内置模板 | 内置 2 个模板 1:1 复刻 `shop_crawl` / `contact_fetch`；灰度跑通，对比旧任务行为等价（事件序列、抓取结果口径） | 同参数下产出一致 |
 | P3 前端看板 | 流水线页 + 只读 DAG 图 + 节点实时看板 + worker 下钻 | 看板实时反映执行 |
 | P4 替代 | 新任务默认走 flow；旧类型冻结（不再加功能），稳定一个周期后下线旧实现 | 旧代码路径删除 |
 | P5 编辑器（v2） | 可视化拖拽编辑 + 保存/校验 | 前端可新建模板 |
 
 ## 10. 明确的非目标（v1 不做）
 
-- 跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度已由 daemon 实现（scheduler-architecture.md §8）
+- 跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度已由 daemon 实现（scheduler-architecture.md §3/§5）
 - 任意条件分支图（if/else 边）；条件能力由策略配置覆盖
 - 模板版本 diff / 回滚（仅支持复制出新模板）
 - 多用户/权限（沿用单机无鉴权前提）
