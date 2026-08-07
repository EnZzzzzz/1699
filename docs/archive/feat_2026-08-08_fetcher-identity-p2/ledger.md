# SDD ledger — plan: docs/feat_2026-08-08_fetcher-identity-p2/PLAN.md

- 分支：feat/fetcher-identity-p2（base main 83120db，main 已含 P0+P1）
- 环境记录：子 Agent 经 `pi -p --model <model>` 独立进程派发（经济=deepseek/deepseek-v4-flash，标准=deepseek/deepseek-v4-pro，终审=deepseek/deepseek-v4-pro）；会话 --session-id 固定便于修复轮 resume；制品全部文件交接（plan 目录）。
- 仓库注意：工作区有另一功能（apify-provider-pairing-login）的未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**P2 全程不碰不提交**，commit 一律 scoped add。

## Step 进度

- Step 1.1: complete (commits cfdca75..5f8764e, review clean)
  - 关键产出：注册名来源结论——插件 name 属性不可用（1688 的 plugin.name='alibaba1688' ≠ 注册名 '1688'），改为 CLI/daemon 透传 site_name；§4 假设 1 被推翻（变更记录已记）；domain→site 映射清单（%1688.com%→1688:、%made-in-china.com%→madeinchina:、%taobao.com%→taobao:、%yiwugo.com%→yiwugo:，先 made-in-china 再 1688）；无法映射第三方域 .mmstat.com(544)/.ynuf.aliapp.org(166) 保持原样；identity 诞生点 browser.py:217/:233，relaunch 不携带旧 identity
  - 首次 review 8 条发现（4C/2I/2M）全是行号错误（implementer 行号系统性偏差），修复轮 1 全部 ADDRESSED；已用 grep -n 逐条实码复核
  - Step 1.1: minor (deferred): browser.py relaunch 范围 :344-384 的右端点 :384 是空白行，方法体实际 :381（文档引用精度，P3 编码阶段可精确化）
- Step 1.2: complete (commits 446effa..892a5e6, review clean)
  - 实现：core/session.py 模块级 bare_identity/is_direct；§3.3 #1-#6 逐条修正（check_ip_fresh 比 bare_identity、loop.py:451 not is_direct、identity_ops is_direct、db.py SQL 双滤、format_tmd_report 列宽 22、fingerprint 传 bare_identity）；TDD 21 新测试
  - 修复轮 1：reviewer 3 条（RED 注释残留、边界测试缺 "" / "a:b:c" / "1688:"、延迟导入改模块级）全部 ADDRESSED；RED 证据主 Agent 已核实（report 内真实断言失败输出）
  - 全量 273 passed；SPEC §5 grep 达成（Python 侧 "direct" 字面量比较只剩 is_direct 内部，db.py SQL 按 §3.3#4 豁免）
- Step 1.3: complete (commits 09fb4c7..d96f977, review clean)
  - 实现：Engine.site_name 新参（site 指定缺 site_name 报错）；BrowserManager.site_name 必传；launch 两处拼前缀（browser.py:221/:237）；CLI args.site / daemon "1688" 透传；测试键格式更新 5 文件；TDD 2 新测试
  - 修复轮 1：reviewer 2 Critical（C1 CLI 装配无测试→_build_engine 抽辅函被两分支调用+3 测试；C2 Engine guard 无测试→3 测试）+ I1 docstring 缺 site_name + M1 or→if/else，全部 ADDRESSED
  - 全量 281 passed；拼键唯一性 grep：f"{self.site_name}:" 仅 browser.py:221/:237
  - **Phase 1 完成**（SPEC §4 假设 1/2 回填 + 核心改造 + 既有测试适配；键已开始带前缀，本 Phase 无运行时冒烟）
- Step 2.1: complete (commits dd6dea5..a7ee816, review clean)
  - 实现：Session.close 回写按 store.domain 过滤（getattr 防御，与 save_from_context 同语义）；_migrate 追加 4 条幂等 UPDATE（madeinchina→1688→taobao→yiwugo 顺序，NOT LIKE '%:%' 守卫，无法映射域保持）；单测 9 条（close 过滤 3 形态 + 迁移四站点/无法映射/幂等/新键 load）
  - review 零 Critical/Important；2 Minor（test_migration.py 死代码 NOW_TS 未引用、_cookie_row helper 未调用）→ 终审分诊
  - 全量 290 passed
- Step 2.2: complete (commits 7439ca8..8782609, review clean)
  - 实现：test_identity_isolation.py 13 测试（① Cookie 各落各桶交叉 load ② burn 一站完好 ③ ip_stats/ip_events 分行 ④ 内存键分开（ip_req/budget_stuck 键级 + burn_ips 真实路径）⑤ 指纹同裸 IP 一致 ⑥ check_ip_fresh 判相等）；定向破坏 RED 证据真实（burn 断言 1→99 亲见 `1 != 99` 红）
  - Step 2.2: parked — reviewer Important-1（④a/④b 键级断言未走 loop 真实路径）：brief 明确允许键级兜底；ip_req/budget 的带前缀键真实路径已在 test_control_loop（Step 1.3 更新）经真实 CrawlLoop 触达，④c burn_ips 已走 SeedBurnTracker 真实路径 —— ruling：真实但延期（Step 3.1 冒烟自然覆盖），不进修复轮
  - Step 2.2: parked — reviewer Important-2（check_ip_fresh 未验证 site_name 串扰）：by design check_ip_fresh 只比 bare IP 不读 site_name（§3.3#1 的本来语义），测试与生产行为逐字相符 —— ruling：reviewer 观察非缺陷
  - Step 2.2: minor (deferred): 跨 store 读注释可能误导（隔离维度是 identity 键不是 store.domain）；mgr 选择 if/else 隐式假设两站点（新增站点时改显式守卫）
  - 全量 303 passed；**Phase 2 完成**（SPEC §5 第 2、4 条达成）
- Step 3.1: 执行中（主 Agent 跑冒烟，证据齐备）
  - 冒烟命令：daemon --db /tmp/ident_smoke.db --workers 1 --limit 2（默认 headless，不加 --headed——本机有活爬虫，PLAN 文本裁定为不适用，report 已记录）
  - 验收①✅（1688:direct 桶 165 行、无裸 direct）；②✅（daemon 口径一致，2 item 因本机 IP 风控全 fail——ip_events 8 条 block_other 全记 1688:direct）；③✅（平台正则对两个带冒号键完整匹配，平台侧零改动成立）
  - ⚠️ 发现（已上报用户）：冒烟 exit 时 `ContactTask.summary()`（contact.py:132，既有代码）不传 db 路径默认开**生产库** → P2 的 _migrate 迁移在生产库提前触发：17385 行带前缀 + 710 裸键（恰为 .mmstat.com 544/.ynuf.aliapp.org 166 无法映射清单，逐域吻合）；总数 18095 不变、迁移完整幂等无数据损失；部署窗口（旧代码白板重启）提前生效，当前无运行中旧代码爬虫。验收④降级为「除一次性设计迁移外零污染」
  - 待用户裁定：summary() 是否小修（thread config.resolved_db_path()，防临时库冒烟再触生产库）
  - Step 3.1: complete——用户裁定「继续」= 同意小修；修复 commit 5fc0dbd（Task.summary 签名加 db_path、engine 传 config.resolved_db_path()、8 处站点实现全改、test_summary_db_path.py +6、engine 装配测试），review 零 Critical/Important（3 Minor：基类 db_path 无类型标注、默认 None 允许省略、3 处无 ShopDB 站点参数未用——终审分诊）；全量 309 passed
  - Step 3.1: minor (deferred): 同上 3 条 Minor
  - **Phase 3 冒烟验收**：①✅ 1688:direct 桶；②✅ 行为与 P1 一致（2 item 因本机 IP 风控全 fail，如实记录）；③✅ 平台正则兼容（平台侧零改动）；④ 生产库零污染 → 降级为「除一次性设计迁移外零污染」（summary 路径提前触发迁移，已修复防复发）
- Step 3.2: complete (commits 2732e78..HEAD, review clean)
  - 文档同步：scheduler-architecture.md §7 四处裁定更新（指纹裸 IP、簿记键前缀零 schema、席位进程级证据、BrowserContext 移 P3）+ §10 P2 行标完成/P3 行补 BrowserContext；fetcher/README.md 补部署窗口提示；SPEC §6 变更记录补 summary 修复条目；AGENTS.md 无 identity 内容免同步
  - 终审（最强模型）：✅ MERGE READY——零 Critical/Important；§3.3 七处逐条 diff 核实；单站点等价性（指纹/check_ip_fresh/直连/报表）逐字成立；迁移与 §3.4 一致；冒烟证据与日志逐项吻合；测试触达矩阵全覆盖（含装配层 _build_engine）；309 passed
  - 终审分诊（全部可延期/非缺陷）：relaunch 行号右端点、test_migration 死代码（NOW_TS/_cookie_row，建议合并后随手清）、④a/④b 键级断言、check_ip_fresh site_name 观察、跨 store 注释、if/else 两站假设、summary db_path 类型标注/默认值/未用参数——均记 ledger，无阻塞项
  - 归档：docs/feat_2026-08-08_fetcher-identity-p2 → docs/archive/（P0/P1 同约定）
