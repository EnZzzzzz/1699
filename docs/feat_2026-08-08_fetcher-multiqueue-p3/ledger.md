# SDD ledger — plan: docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md

- 分支：feat/multiqueue-p3（base main b127c84）
- 环境记录：子 Agent 经 `pi -p --provider deepseek --model <model>` 独立进程派发（经济=deepseek-v4-flash，标准=deepseek-v4-pro，终审=deepseek-v4-pro）；会话 --session-id 固定便于修复轮 resume；制品全部文件交接（plan 目录）。
- 仓库注意：工作区有另一功能（apify-provider-pairing-login）的未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**P3 全程不碰不提交**，commit 一律 scoped add。

## 主 Agent 裁定（冲突扫描，2026-08-08，开工前一次性裁决）

1. **Step 1.3 让出型改造范围**：PLAN 文本同时写「策略冷却登记即返回」与「策略冷却后 item 未完成的路径暂保留现状」——若策略冷却（block_rest 等）登记即返回，`_process_item` 策略链会立即重试同一 item 形成无限快速循环。裁定：Step 1.3 只把 loop 三处节奏冷却（sample_interval / batch_rest / periodic_rest）改为让出型（登记 site 键后立即返回，等待转移到 acquire_item 的 condvar timeout=min(最近冷却到期剩余, 30s)）；策略冷却 + launch_backoff 保持原地等待（策略冷却待 P3-3 router 接 release 后改让出，符合 SPEC §3.4 落地时序）。
2. **Step 1.2 前向依赖**：`eligible_queues` 的 registry 正式定义在 Step 3.1。裁定：Step 1.2 以纯函数 + duck-typed registry 实现（SimpleNamespace 模拟 QueueSpec 单测），Step 3.1 建真实注册表复用。
3. **P3-1 单队列等价性口径**：让出型冷却后等待从 loop 内移到 acquire_item condvar，总节奏等价；状态行展示从「样本间隔 Ns」变为「等货/等冷却」。冒烟按节奏等价判定，不按展示文案。
4. **P3-3 loop 多 site 绑定**（SPEC §6.8）：CrawlLoop 的 `SceneInspector.for_site(ctx.site)`（loop.py:81）与 `self.policy` 在 __init__ 固定；P3-3 需 per-item site 绑定（router acquire 后绑 ctx.site/ctx.policy，loop 按 active_site 切换 inspector/policy）。Step 3.1 brief 必须写明。
5. **`_cooldown` 键语义变更**：test_cooldown.py 5 处断言 reason 键（:217/:232/:267/:351/:379），改 site 键须同步更新；原地型（launch_backoff/策略冷却）不写 site 键（等待期间消费者本就不可用）。
6. **`Engine._alloc_seed_kits` daemon/CLI 共用**：P3-2 改 (worker,site) 粒度只影响 daemon 路径，CLI 单站点保持现状。
7. **`Session.close` 双层语义的 Cookie 域过滤**：IdentityStore.domain 单站点属性，save_from_context 按 store.domain 子串过滤；多 context 后 close_site(site)/save_cookies 需按各 site 的 cookie_domain 过滤。P3-2 核心设计点。

## Step 进度

### P3-0（spike，C1 验证）

- Step 0.1: complete (commit bdef641, review clean)
  - 实现：脚本 /tmp/spike_cloak_multicontext.py 实测 get_active_session_count 序列；主 Agent 独立复跑确认（n0=0→n1=1→n2=1→n3=1→n4=0，delta=1/0/-1 逐条命中）；报告 docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
  - **C1 已验证**（SPEC §4 C1 已回填）；P3-2 准入达成，浏览器层可动工
  - review 零 Critical/Important；3 Minor（n0=0 与 brief 环境假设出入——已诚实记录且不影响结论；表格冗余；报告未附终端原始输出——主 Agent 已亲跑脚本验证一致）→ 记 ledger，不进修复循环
  - Step 0.1: minor (deferred): 同上 3 条 Minor

### P3-1（调度内核）

- Step 1.1: complete (commits c87c616..d682282, fix round 1/5 clean)
  - 实现：db.py _migrate 补 attempts 幂等迁移 + release_work_item + claim_next_eligible（TDD 9 新用例，全量 318→319 passed）；现有 work_items 方法未动
  - fix round 1/5: review 2 Important（① claim_next_eligible json.loads 在 try 外/commit 后——非法 payload 时行已 claimed 拿不到返回，永久泄漏；② SELECT * 脆弱性）+ 2 Minor（rowcount=0 路径 commit 一致性、返回位置不对称）→ resume implementer 修复 commit d682282（解析移入事务内，非法 JSON → rollback 行保持 pending；显式列；rollback 统一；新泄漏测试 RED→GREEN）；re-review 全部 ADDRESSED 零新破坏
  - Step 1.1: minor (deferred): 无
  - 注：dispatch prompt 曾因反引号被 bash 命令替换破坏（子 Agent 仍正确理解修复目标）——后续 prompt 避免反引号
- Step 1.2: complete (commit ebd16ba, review clean)
  - 实现：context.py（cooldown_until 键改 site 语义 + resources 字段默认 {channel,browser}）；control/queue_router.py 新建（QueueSpec 三字段 + eligible_queues + condvar_timeout 两纯函数）；loop._cooldown 写 active_site 键（未设不登记）；daemon_task proxy claim 冷却过滤 + condvar timeout + active_site 写入（TDD 17 新用例，全量 319→336 passed）
  - review 零 Critical/Important；2 Minor（eligible_queues 类型标注不一致→P3-3 补齐；test_cooldown_blocks_claim 时序 0.15s 缓冲无下界）→ 记 ledger，不进修复轮
  - Step 1.2: minor (deferred): 同上 2 条 Minor
- Step 1.3: complete (commits 8aef518..feb7c95, fix round 1/5 clean)
  - 实现：loop._cooldown 加 yield_ 参数——让出型（sample_interval/batch_rest/periodic_rest）登记 site 键后立即返回；原地型（launch_backoff/策略冷却）保持等待 + 注释；strategies.py SwapIP「P3 重议」→「P3-3 改让出」同步；TDD 5 新用例 + fix 轮 +1 集成测试（全量 336→342 passed）
  - fix round 1/5: review 需修复——F1 (Important) 冒烟未触达让出型节奏冷却（直连滑块墙 abort）→ B 方案补成功路径集成测试（CrawlLoop+DaemonTaskProxy 假基建，断言等待发生在 acquire condvar、loop 内无 ctx.wait，report 如实声明）；F2 注释检查未记录→已核实 context.py 无残留 + strategies.py 同步；F3 缺 negative 断言→补 launch_backoff/策略冷却 yield_=False 断言；F4/F5/F6 文档/注释 minor；全部 ADDRESSED，零新破坏
  - **Phase 1（P3-1）完成**：冷却表 site 键 + eligible_queues/condvar_timeout + 让出型 chokepoint + work_items attempts/release/claim_next_eligible；342 passed；单队列 daemon 冒烟结构证据（smoke-step1.3/）
  - Step 1.3: minor (deferred): 无

### P3-2（浏览器层多 context，准入：C1 已验证）

- Step 2.1: complete (commits 274842b..82683a9, fix round 1/5 clean)
  - 实现：Session 重构（views dict + SiteView + _active_site 路由 + set_active_site + close_site/close 两层）；BrowserManager.ensure_site 懒建（Cookie 装载段与 launch 逐字一致）+ launch 建初始 view + warmup per-view（签名向后兼容旧形态）+ save_cookies 遍历全部 views + relaunch 全 view 回写；IdentityStore.save_from_context 加 domain 参数；TDD 37 新用例（全量 342→379 passed）
  - fix round 1/5: review 需修复——F1 (阻断) 冒烟证据不实（人工注释非 raw 输出）→ 重新真实冒烟 smoke-fix1-raw.txt（60 行 raw：launch→创建初始 view→Cookie 装载→滑块求解全链路）；F2 (阻断) warmup 签名破坏性变更→旧形态可调用兼容；F3 ensure_site 重复查 IP + req_proxies None 静默回退→IP 缓存 + 防御；F4 域过滤重复→_write_view_cookies 提取；F5 report 修正；全部 ADDRESSED 零新破坏
  - Step 2.1: minor (deferred): _write_view_cookies 签名 log 参数未使用（Trivial）
  - 注：本 Step 冒烟显示直连 1688 滑块墙在 solve 阶段连续失败（环境噪声，已如实记录）
- Step 2.2: complete (commits 564659b..c13f564, fix round 1/5 clean)
  - 实现：mark_needs_relaunch/clear_needs_relaunch + ensure_site 懒建消费（置位→完整 relaunch→清除）；_alloc_seed_kits(workers, sites=None) 多站点 (worker,site) 粒度（CLI sites=None 返回 list 逐字不变）；TDD 16 新用例（全量 379→395 passed）
  - fix round 1/5: review 需修复——C1 (Critical) seed_x5sec 多站点路径 0 覆盖→补两站点+sites 非空 A/B 断言；I2 Session 状态迁移字段逐一拷贝脆弱→copy_state_from 集中迁移；I3 缺 clear_needs_relaunch(site)→加 API 成对 + 单测；M4 无效测试→改 API；M5 类型注解；全部 ADDRESSED 零新破坏
  - **Phase 2（P3-2）完成**：Session views 多 context + ensure_site 懒建 + needs_relaunch + 种子池 (worker,site)；395 passed；单站点等价（smoke-step2.1/smoke-fix1-raw.txt）
  - Step 2.2: minor (deferred): 无

### P3-3（QueueRouter + SwapIP）

- Step 3.1: complete (commits 6312302..f86b80b, fix round 1/5 clean)
  - 实现：QueueRouter 取代 DaemonTaskProxy（git rm daemon_task.py）；QueueSpec 补全（task/topup/domain_suffix）；acquire 三段式（claim_next_eligible→逐队列 topup（冷却到期才补）→condvar）；on_success/on_giveup 路由 + finish；budget_for 协议（Task 基类默认 ip_request_budget）；loop _bind_item_site（sites/policies 注入，per-item 切 inspector/policy）；Engine sites/policies 透传；CLI --queues（删 --queue）+ reset 逐 site domain 过滤（提取 reset_daemon_state）；TDD 29 新用例（全量 395→404 passed）
  - fix round 1/5: review 需修复——I1 Step 1.2 纯函数单测被整段删除→从 git 找回恢复（12 边界用例）；I2 reset 逐 site 无测试→补两 domain 各自重置测试；I3 --queues 硬编码→_build_registry 动态派生 + choices 动态；M4/M5/M6（注释/payload id 确认无依赖移除/condvar_timeout 删除）；全部 ADDRESSED（全量 404→420 passed）
  - Step 3.1: minor (deferred): 无
- Step 3.2: complete (commits 5c1afe8..6ff09e1, fix round 1/5 clean)
  - 实现：SwapIP 无头两阶段（relaunch 未轮换→回写+close_site+mark_needs_relaunch+让出冷却；有头例外保留原地+注释）；loop 策略冷却改「让出 + release」（kind=release，不计数，QueueRouter.release_item → release_work_item attempts 熔断）；Task 基类 release_item 默认空实现；TDD 18 新用例（全量 420→438 passed）
  - 注：implementer 超时未写 report/commit，主 Agent 已代 commit 5c1afe8 并核实范围（未碰用户文件）；reviewer 以 diff 为准
  - fix round 1/5（新 implementer，原 implementer 失联）：I1 (防御性) step.cooldown 无条件优先 solved→加 not step.solved 守护+注释；M1 site=None 静默耗尽→WARNING+不输出 cooldown；M2 ctx.wait 断言；M3 result_json 断言去耦合；全量 438→440 passed，全部 ADDRESSED 零新破坏
  - Step 3.2: minor (deferred): 无
- Step 3.3: complete (commits 7595c5b..dd599ce, fix round 1/5 clean)
  - 实现：跨站 view 懒建补缺（loop._bind_item_site 补 ensure_site + set_active_site + try/except 容错，TDD 5 用例）；双队列跨站冒烟（Run 5 双向手递手取证：1688#1 failed 17:39:38 → mic#1 claimed 同秒 → mic#1 done → 1688#2 claimed 同秒 → 1688#2 failed → mic#2 claimed，两轮双向）
  - **debug 子任务（p3-3-debug1）**：冒烟发现 worker 异常退出 'empty'/'failed'（KeyError）→ traceback 定位根因：QueueRouter.make_stats 返回 {done:0} 与 contact task 的 {ok,empty,failed} 键不符 → **P3 引入**（非预存）→ 修复 ca35d5e（make_stats 合并所有 task 统计键 + rest_counter 委托首个 task + loop except 加 traceback 打印产品改进保留）；TDD +3，全量 445→447 passed
  - fix round 1/5: review 需修——C1 _bound_site 在 plugin 块内设（改无条件设）；C2 report 误标预存（改 P3 引入已修）；I3 补 Run 5 取证（dd599ce）；M5/M6 import 位置/截断；全部 ADDRESSED 零新破坏
  - **取证口径记录**：Run 5 证明跨站切换机制（同 worker 一站处理完转另一站，双向）；「冷却登记后到期前」的严格取证（sample_interval 让出冷却窗口内认领另一站）留 **P3-6 Step 6.1** 补（届时放大样本间隔制造冷却窗）
  - **Phase 3（P3-3）完成**：QueueRouter + 双队列注册表 + SwapIP 两阶段 + 跨站懒建；447 passed；跨站双向手递手取证
  - Step 3.3: minor (deferred): 无

### P3-4（madeinchina 队列接入）

- Step 4.1: complete (commits 54ecb07..8daf5a1, fix round 1/5 clean)
  - 实现：MadeInChinaShopTask 重构为 work_items 驱动 feeder（payload category/discover；page_no 运行时读 next_page；链式续喂 advance/mark_exhausted 含 ZERO_NEW_LIMIT；discover 走 on_success 提取类目插 category item；refill_item 失败补插 + Task 基类默认空；CLI acquire 改 claim_next_eligible([crawl_mic_shop])；prepare 幂等播种）；QueueRouter.release_item 接 refill；crawl_mic_contact 注册/逐 site reset/域过滤复核确认（均已有）；TDD 19 新用例（全量 447→462 passed）
  - fix round 1/5: review 需修复——C1 (Critical) validate 拒绝 discover（无 shops 键→False→giveup，生产路径封死）→ validate 对 discover 检查 discover 键放行；I2 discover 测试绕过 validate→补 fetch→validate→on_success 三段式测试；M3 fmt 硬编码 x2 局限注释（Step 4.2 议）；M4 _count_pending_by_kind 抽取；M5 移除 _now 私有导入；全部 ADDRESSED（全量 462→463 passed）
  - Step 4.1: minor (deferred): M3 fmt=x2 播种局限（plain 类目 URL 拼错，discover 可纠正；Step 4.2 评估是否加 fmt 列）
- Step 4.2: complete (commits 379b8c9..14c92d4, fix round 1/5 clean)
  - 实现：db.py iter_active_categories(prefix=) 统一查询（get_active_categories 改造为调它 + 拼音过滤，返回结构兼容）；cli/main.py 注册表加 crawl_mic_shop（topup=None, domain_suffix=""）+ reset 精确化（只对 topup 非 None 队列 reset_in_progress）；shop.py 播种切 iter_active_categories；TDD 5 新用例（全量 463→468 passed）
  - fix round 1/5: review 需修——I1 shop.py 导入 db 私有 _is_pinyin_slug→本地复制 regex；I2 冒烟取证不足→sqlite3 只读查询补证（category=1053 pending+2 done、jgdbj next_page=2 pages=1 shops=15、shops 落库 15 pending、链式续喂页 2 item 已插入）；M3 docstring；M4 结构断言；全部 ADDRESSED 零新破坏
  - **冒烟取证（smoke-step4.2/）**：空库启动→播种 discover→提取 ~360 类目→jgdbj 类目页真实抓取 15 家店铺→category_progress 推进→链式续喂页 2 item；feeder 队列不触发 in_progress reset
  - **Phase 4（P3-4）完成**：crawl_mic_contact（Step 3.1 已入）+ crawl_mic_shop feeder 链路（播种→discover→类目页→链式续喂）；468 passed
  - Step 4.2: minor (deferred): 无
