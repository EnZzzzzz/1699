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
