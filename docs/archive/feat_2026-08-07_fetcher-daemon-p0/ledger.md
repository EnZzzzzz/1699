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
- Step 2.4: complete（走查 Step，无代码 commit；证据 task-2.4-report.md + /tmp/daemon_smoke_{b,c}.log，主 Agent 已抽查日志与生产库零污染）
  - Step 2.4: 计划外发现（既有 bug，非 daemon 引入）: ContactTask.summary() 用无参 ShopDB() 忽略 --db，收尾报表读生产库（contact.py:132，只读）→ 待按 issue-create 流程处理，终审分诊
  - Step 2.4: minor (deferred): 非 tty 下 stdout 块缓冲，运行中途日志为空（建议 -u 或 logging flush，非本次范围）
  - Step 2.4: 环境噪音记录: CloakBrowser 席位 5/5 被本机其他爬虫占用时启动会等席位（每 20s 重查），非 bug
- Step 3.1: complete（走查 Step，无代码 commit；证据 task-3.1-report.md + /tmp/equiv_*.log，主 Agent 已全文核实报告）
  - 主 Agent 裁定：SPEC §5 第 2 条「work_items 全 done」字面未达成（18 done + 2 failed，登录墙密集期策略链正常放弃，A 组同环境 1 failed）→ 验收放宽为「全部落正确终态」，已记入 SPEC §6 变更记录
  - 等价性结论：节奏 2.08 vs 2.64 个/分钟（同量级，差异=风控等待）；成功产出 17 家完全相同；共有 contacts 14/17 逐字段全等、3 家为软拦截内容差异，无「同字段不同值」
  - 现场观察：测试进程与活 madeinchina 爬虫经共享隧道缓存拿到同一出口 IP（跨站，无实际危害）——正是 scheduler-architecture §2 所述「无协调撞车」的实证
  - Step 3.1: 计划外发现（既有 bug）: ContactTask.summary() 无参 ShopDB() 读生产库 + 构造时对生产库执行幂等 DDL/_migrate（与 2.4 发现同源）
  - Step 3.1: minor (deferred): 非 TTY 下常规行只上状态板不进日志文件（既有行为，可观测性改进点）
- Step 3.2: complete (commits a35a842..56953e9, review clean)
  - Step 3.2: minor (deferred): README「--limit N 跑完 N 个后退出」是 per-worker 口径简写（多 worker 总量 N×workers），终审修复轮顺手改严谨
- Step 3.3: complete (终审 commits 66fde5d..4837613 全分支通过；修复轮 4837613..5a54987，re-review clean)
  - 终审结论：通过。旧代码路径零改动逐文件核实；db/proxy/CLI 三处接口咬合一致；非目标防线守住；SPEC §5 四条验收均有归档证据
  - 终审修复（5a54987）：daemon_task.py docstring 示例（queue/domain_suffix 口径）+ README --limit per-worker 口径
  - 终审分诊（合并后跟进）：prepare 不走 db_factory；daemon --retry-failed；--queue 加 choices 收紧；stdout 缓冲/日志可观测性
  - 终审分诊（转 issue，既有 bug 非本分支引入）：ContactTask.summary() 无参 ShopDB() 忽略 --db（contact.py:132，建议 P2）——待用户确认后按 issue-create 开 issue
  - 不用修（带 ruling）：on_success 异常残留 claimed（重启回收兜底）；condvar 单锁串行（毫秒级短事务）；finish 不校验 status（内部字面量调用）
