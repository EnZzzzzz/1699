# SDD ledger — plan: docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md

- 分支：feat/fetcher-daemon-p0（base main 66fde5d）
- Setup commit：e50270b（docs：scheduler-architecture + SPEC/PLAN）
- 环境偏差记录：本环境 Agent 工具无模型选择参数，implementer/reviewer 均用默认 coder 类型派发，无法显式降档。

## Step 进度

- Step 1.1: complete (commits e50270b..8a3db10, review clean)
  - Step 1.1: minor (deferred): report 称 isinstance grep 命中 13 处，实际 14 处（计数小误差，不影响结论）
  - Step 1.1: minor (deferred): report 内 cold_start 差异裁定未回引 SPEC §3.3（两处表述一致，追溯需跨文件）
  - 主 Agent 裁定（8a3db10）：cold_start dict/Row 分支差异接受为已知等价性偏差，已写入 SPEC §3.3
- Step 1.2+1.3: complete (commits 10b4b47..8fcfe91, review clean)
  - Step 1.2+1.3: minor (deferred): 未覆盖 name/url 为 NULL 时 payload 三键仍在的用例（代码按 dict 字面量构造保证，审查确认可靠）
  - Step 1.2+1.3: minor (deferred): 用例 2 顺序模拟并发，真并发互斥依赖「与 claim_pending_shops 同模式」论证（brief 许可）
  - Step 1.2+1.3: minor (deferred): claim 的 payload 解析在 commit 之后，payload 损坏会抛异常（无事务悬挂，当前唯一写入方是 topup）
  - Step 1.2+1.3: minor (deferred): finish_work_item 不校验 status 取值域（brief 未要求）
- Step 2.1: complete (commits cd4d023..f6034dd, review clean)
  - Step 2.1: minor (deferred): 临时冒烟脚本未入库（正式测试归 Step 2.2）
  - Step 2.1: minor (deferred): prepare 不走 db_factory，直接 ShopDB(config.resolved_db_path())
  - Step 2.1: minor (deferred): inner.on_success 抛异常时 work_item 残留 claimed（重启回收兜底，取舍可接受）
  - Step 2.1: minor (deferred): 单一条件变量锁串行化所有 worker 的 claim/topup（P0 规模无需处理）
- Step 2.2: complete (commits 6794d64..1af732b, review clean)
  - Step 2.2: minor (deferred): 用例 2 无 stop/deadline 兜底，regression 时可能挂起而非失败
  - Step 2.2: minor (deferred): 用例 4 stray on_success 对 inner.succeeded 有未断言的副作用
  - Step 2.2: minor (deferred): 用例 5 worker 异常被 loop 吞掉后诊断信息少一层（终态断言+deadline 仍可抓住）
- Step 2.3: complete (commits f955498..e377a29, review clean)
  - 主 Agent 裁决（执行前）：daemon parser 补挂 -n/--num 与 --limit、main() 调 task.prepare(cfg)，两点偏差均必要且符合 SPEC 意图
  - Step 2.3: minor (deferred): daemon 分支 Engine(cfg, task=task,...) 关键字传参 vs 站点分支位置传参（语义等价）
  - Step 2.3: minor (deferred): daemon parser 无 --retry-failed 开关（getattr 容错为 False，后续需要再挂）
  - Step 2.3: minor (deferred): daemon_task.py:36 docstring 示例 domain_suffix="1688.com" 少个点（正确口径 ".1688.com"），终审时修
