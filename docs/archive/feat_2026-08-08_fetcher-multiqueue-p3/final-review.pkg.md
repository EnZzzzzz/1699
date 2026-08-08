# 全分支终审审查包 — feat/multiqueue-p3

## MERGE_BASE: b127c84 (main)  HEAD: 966000d

## Commits (43)
966000d docs(multiqueue-p3): P3-6 Step 6.2 文档同步——SPEC §7 勾选 + README daemon 队列清单 + scheduler §10 P3 行标完成
6bdf1ab docs(multiqueue-p3): Step 6.1 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
9fff6a0 P3 Step 6.1 Fix Round 1: claim/finish 日志 + TDD + 重跑冒烟取证
8250c02 P3 Step 6.1: 跨站填充端到端冒烟 — 5 队列 + 双队列验收取证
c80a3d2 docs(multiqueue-p3): P3-5 Phase 完成（Step 5.2 + ledger/PLAN/review 包）
cb42588 fix(multiqueue-p3): step5.2 review fixes — company smoke + DB evidence + feeder test
6fd3117 feat(multiqueue-p3): add crawl_1688_shop/company to registry (5 queues complete)
64eecc4 docs(multiqueue-p3): Step 5.1 完成——ledger/PLAN/review 包入库
3fedf72 feat(multiqueue-p3): 1688 shop/company feeder 任务拆分（work_items 驱动）
f95db2b docs(multiqueue-p3): P3-4 Phase 完成（Step 4.2 + ledger/PLAN/review 包）
14c92d4 fix(multiqueue-p3): I1 移除私有函数导入 I2 DB取证 M3 docstring M4 结构断言
379b8c9 feat(multiqueue-p3): iter_active_categories 统一查询 + crawl_mic_shop 注册表 + reset 精确化
42b3aca docs(multiqueue-p3): Step 4.1 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
8daf5a1 fix(multiqueue-p3): C1 validate discover pass-through + I2/M3/M4/M5
54ecb07 feat(multiqueue-p3): refactor MadeInChinaShopTask to work_items-driven feeder
a73c322 docs(multiqueue-p3): P3-3 Phase 完成（Step 3.3 + debug 修复 + ledger/PLAN/review 包）
dd599ce fix(multiqueue-p3): Step 3.3 review fix — C1/C2/I3/M5/M6
ca35d5e fix(multiqueue-p3): QueueRouter.make_stats 合并所有注册 task 统计键，修复 KeyError('empty'/'failed')
7595c5b feat(multiqueue-p3): Step 3.3 跨站 view 懒建补缺 + 双队列跨站填充冒烟
9349f7e docs(multiqueue-p3): Step 3.2 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
6ff09e1 fix(multiqueue-p3): Step 3.2 review 修复 I1/M1/M2/M3（solved 守护、site=None 防御、ctx.wait 断言、result_json 去耦合）
53f14cd docs(multiqueue-p3): task-3.2 brief 入库
5c1afe8 feat(multiqueue-p3): SwapIP 两阶段拆分 + 策略冷却让出/release 链路（TDD 18 新用例，438 passed）
085d4e6 docs(multiqueue-p3): Step 3.1 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
f86b80b fix(multiqueue-p3): I1恢复纯函数单测+I2 reset逐site测试+I3 --queues动态校验+M4/M5/M6
6312302 feat(multiqueue-p3): QueueRouter取代DaemonTaskProxy，多队列注册表装配，daemon CLI --queues
4d83abc docs(multiqueue-p3): PLAN 勾 Step 2.2 + P3-2 Phase done
0bf271c docs(multiqueue-p3): P3-2 Phase 完成（Step 2.2 + ledger/PLAN/review 包）
c13f564 fix(multiqueue-p3): task-2.2 fix1 — C1/I2/I3/M4/M5
564659b feat(multiqueue-p3): needs_relaunch 状态位 + 种子池 (worker,site) 粒度
3ea9597 docs(multiqueue-p3): Step 2.1 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
82683a9 fix(multiqueue-p3): Fix1 — warmup 签名兼容 + IP 缓存 + DRY Cookie 回写 + 真实冒烟证据
274842b feat(multiqueue-p3): Session/SiteView 多 context 重构——views 路由 + 两层关闭 + ensure_site（TDD 37 新用例，379 passed）
d6647d9 docs(multiqueue-p3): P3-1 Phase 完成（Step 1.3 + ledger/PLAN/review 包）
feb7c95 feat(multiqueue-p3): fix F1-F6 — 让出型集成测试 + 注释/断言补全
8aef518 feat(multiqueue-p3): _cooldown 让出型改造——节奏冷却登记即返回
53f4ce6 docs(multiqueue-p3): Step 1.2 完成——ledger/PLAN/review 包入库
ebd16ba feat(multiqueue-p3): cooldown key to site + eligible_queues + claim filter with condvar_timeout
309e556 docs(multiqueue-p3): Step 1.1 完成（修复轮 1 全清）——ledger/PLAN/review 包入库
d682282 fix(multiqueue-p3): review 修复——claim_next_eligible 非法 payload 不泄漏（解析入事务前）+ 显式列 + release rowcount=0 rollback（319 passed）
3617fce docs(multiqueue-p3): P3-0 spike 完成——C1 已验证回填 SPEC §4 + ledger/brief/review 入库
c87c616 feat(multiqueue-p3): work_items 扩展——attempts 幂等迁移 + release_work_item + claim_next_eligible（TDD 全绿 318 passed）
bdef641 P3-0 Step 0.1: CloakBrowser 多 context 席位计数实测 — C1 已验证

## Stat
 docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md |  105 +
 docs/feat_2026-08-08_fetcher-multiqueue-p3/SPEC.md |  201 ++
 .../debug-brief.md                                 |   42 +
 .../debug-worker-crash.md                          |  112 +
 .../ledger.md                                      |  109 +
 .../smoke-step1.3/smoke-analysis.md                |   60 +
 .../smoke-step1.3/smoke-output.txt                 |    9 +
 .../smoke-step2.1/smoke-fix1-raw.txt               |   60 +
 .../smoke-step3.3/analysis.md                      |  130 +
 .../smoke-step3.3/daemon-run-1.log                 |   26 +
 .../smoke-step3.3/daemon-run-2.log                 |   21 +
 .../smoke-step3.3/daemon-run-3.log                 |   24 +
 .../smoke-step3.3/daemon-run-4.log                 |   21 +
 .../smoke-step3.3/daemon-run-5.log                 |   25 +
 .../smoke-step4.2/analysis.md                      |  111 +
 .../smoke-step5.2/analysis.md                      |  186 ++
 .../smoke-step5.2/company-run.log                  |  124 +
 .../smoke-step6.1/run-double.log                   |   35 +
 .../smoke-step6.1/run.log                          |   47 +
 .../spike-cloakbrowser-multicontext.md             |   77 +
 .../task-0.1-brief.md                              |   58 +
 .../task-0.1-review.md                             |  158 ++
 .../task-1.1-brief.md                              |   92 +
 .../task-1.1-fix1-review.md                        | 1265 +++++++++
 .../task-1.1-report.md                             |  146 ++
 .../task-1.1-review.md                             |  402 +++
 .../task-1.2-brief.md                              |   99 +
 .../task-1.2-report.md                             |  120 +
 .../task-1.2-review.md                             |  724 ++++++
 .../task-1.3-brief.md                              |   98 +
 .../task-1.3-fix1-review.md                        |  617 +++++
 .../task-1.3-fix1.md                               |   51 +
 .../task-1.3-report.md                             |  155 ++
 .../task-1.3-review.md                             |  386 +++
 .../task-2.1-brief.md                              |  140 +
 .../task-2.1-fix1-review.md                        |  472 ++++
 .../task-2.1-fix1.md                               |   52 +
 .../task-2.1-report.md                             |   85 +
 .../task-2.1-review.md                             | 1526 +++++++++++
 .../task-2.2-brief.md                              |   83 +
 .../task-2.2-fix1-review.md                        |  341 +++
 .../task-2.2-fix1.md                               |   43 +
 .../task-2.2-report.md                             |  138 +
 .../task-2.2-review.md                             |  840 ++++++
 .../task-3.1-brief.md                              |  119 +
 .../task-3.1-fix1-review.md                        |  612 +++++
 .../task-3.1-fix1.md                               |   47 +
 .../task-3.1-report.md                             |  120 +
 .../task-3.1-review.md                             | 2690 ++++++++++++++++++++
 .../task-3.2-brief.md                              |  144 ++
 .../task-3.2-fix1-review.md                        |  575 +++++
 .../task-3.2-fix1.md                               |   42 +
 .../task-3.2-report.md                             |  113 +
 .../task-3.2-review.md                             | 1162 +++++++++
 .../task-3.3-brief.md                              |   97 +
 .../task-3.3-fix1-review.md                        |  272 ++
 .../task-3.3-fix1.md                               |   52 +
 .../task-3.3-report.md                             |  141 +
 .../task-3.3-review.md                             |  812 ++++++
 .../task-4.1-brief.md                              |   81 +
 .../task-4.1-fix1-review.md                        |  304 +++
 .../task-4.1-fix1.md                               |   45 +
 .../task-4.1-report.md                             |  149 ++
 .../task-4.1-review.md                             | 1581 ++++++++++++
 .../task-4.2-brief.md                              |   96 +
 .../task-4.2-fix1-review.md                        |  263 ++
 .../task-4.2-fix1.md                               |   38 +
 .../task-4.2-report.md                             |  137 +
 .../task-4.2-review.md                             |  602 +++++
 .../task-5.1-brief.md                              |   79 +
 .../task-5.1-report.md                             |  132 +
 .../task-5.1-review.md                             | 2213 ++++++++++++++++
 .../task-5.2-brief.md                              |   88 +
 .../task-5.2-fix1-review.md                        |  457 ++++
 .../task-5.2-fix1.md                               |   33 +
 .../task-5.2-report.md                             |   83 +
 .../task-5.2-review.md                             |  322 +++
 .../task-6.1-brief.md                              |   62 +
 .../task-6.1-fix1-review.md                        |  473 ++++
 .../task-6.1-fix1.md                               |   46 +
 .../task-6.1-report.md                             |  349 +++
 .../task-6.1-review.md                             |  316 +++
 docs/scheduler-architecture.md                     |    2 +-
 fetcher/README.md                                  |   26 +-
 fetcher/fetcher/__init__.py                        |    2 +
 fetcher/fetcher/cli/main.py                        |  171 +-
 fetcher/fetcher/control/daemon_task.py             |  195 --
 fetcher/fetcher/control/engine.py                  |   55 +-
 fetcher/fetcher/control/loop.py                    |  116 +-
 fetcher/fetcher/control/queue_router.py            |  330 +++
 fetcher/fetcher/control/task.py                    |   22 +
 fetcher/fetcher/core/__init__.py                   |    3 +-
 fetcher/fetcher/core/context.py                    |    9 +-
 fetcher/fetcher/core/session.py                    |  171 +-
 fetcher/fetcher/db.py                              |  111 +-
 fetcher/fetcher/net/browser.py                     |  241 +-
 fetcher/fetcher/net/identity.py                    |    9 +-
 fetcher/fetcher/sites/alibaba1688/__init__.py      |    8 +-
 fetcher/fetcher/sites/alibaba1688/company.py       |  315 ++-
 fetcher/fetcher/sites/alibaba1688/shop.py          |  302 ++-
 fetcher/fetcher/sites/madeinchina/shop.py          |  326 ++-
 fetcher/fetcher/strategy/strategies.py             |   64 +-
 fetcher/tests/test_1688_feeder.py                  | 1072 ++++++++
 fetcher/tests/test_cli.py                          |  209 +-
 fetcher/tests/test_control_loop.py                 |  199 ++
 fetcher/tests/test_cooldown.py                     |  363 ++-
 fetcher/tests/test_daemon_task.py                  |  367 ---
 fetcher/tests/test_engine.py                       |  257 ++
 fetcher/tests/test_madeinchina.py                  |  315 ++-
 fetcher/tests/test_mic_shop_feeder.py              |  599 +++++
 fetcher/tests/test_needs_relaunch.py               |  320 +++
 fetcher/tests/test_queue_router.py                 | 1107 ++++++++
 fetcher/tests/test_session_views.py                |  719 ++++++
 fetcher/tests/test_swapip_two_phase.py             |  803 ++++++
 fetcher/tests/test_work_items.py                   |  241 +-
 115 files changed, 32430 insertions(+), 1182 deletions(-)
