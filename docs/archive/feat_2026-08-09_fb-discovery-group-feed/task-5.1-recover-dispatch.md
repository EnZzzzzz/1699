你正在执行 Step 5.1 的收尾恢复（第 2 阶段）：恢复 daemon local 消费者 + 补验 wa_check 观察（验收 4）。

## 背景（协调者已定位根因，勿重复调查）

Step 5.1 首轮冒烟 BLOCKED：daemon 的 local 消费者（local0/local1）在 23:48 处理
crawl_fb_group 的 FATAL（缺 BRIGHTDATA_API_KEY）后停摆。**根因（已确认）**：
`fetcher/fetcher/control/local_loop.py` 的 FATAL 分支执行 `on_giveup(fatal)` →
`set_status("FATAL，退出")` → `break` → `_local_worker` 线程结束；`engine.run` 主循环
只 `join` local 线程**不重启**——这是既有框架设计（wa_check 注释「FATAL→停止」= 不可
自愈环境错误停消费者），本 feature 首次多 local 队列把它暴露：fb_group 缺 key 的
FATAL 连坐停掉 discover_fb（不需要 key）。**非本 feature 代码 bug，不改代码。**

## 你的工作

### 1. 恢复 daemon（运维操作，不改代码）
- 当前 daemon PID 30019（父）/30020（子）在跑但 local 消费者已停。用
  `platform/stop.sh` 停止，再 `platform/start.sh` 起新的（report 疑虑：bash 工具调用
  start.sh 会挂——用 `nohup bash platform/start.sh > /tmp/fb_recover_start.log 2>&1 &`
  脱离调用 shell）。
- 验证：新 daemon 日志出现 8 队列注册 + local 消费者启动
  （`[2] 另启动 2 个 local 消费者`）；consumer_status 有 local0/local1 活跃。

### 2. 补验验收 4（wa_check 观察，零改动链路）
目标：验证「新落的 fb_contacts 号码自动进 wa_check 队列」（SPEC §10 验收 4）。
- 方法：手工 INSERT 1 条带号码的 fb_posts（cn_uncertain 桶号码，如
  `https://www.facebook.com/groups/999/posts/888` + 号码 13800138000）→ 创建
  fb_post 任务（limit=1）→ start → 等 crawl_fb_post 消费 → fb_contacts 出现该号
  （bucket=cn_uncertain）→ 观察 wa_check work_items 是否出现该号（wa_check topup
  30s 唤醒挑号）。**只观察，零代码改动**。完成后清理：删任务、停批次、把手工
  插入的行标记清理（report 写明清理方式）。
- 若 wa_check 因账号 403 无法实际查号（既有问题），观察「该号进入 wa_check 队列
  pending」即可满足验收 4（链路涵盖 = 入队，查号失败是既有账号问题）。

### 3. 冒烟记录追加 + commit
- 把恢复 + 验收 4 补测记录**追加**到 ledger.md（Step 5.1 记录下新增小节）。
- 同时更新 ledger 的 Step 5.1 判定：验收 1/2/3/5 满足（首轮已证）、验收 4 本阶段
  补验结果。
- commit：只 add ledger.md + report（禁止 -A）。

## 报告格式

完整报告**追加**到 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.1-report.md`（或新建 task-5.1b-report.md）：
- 恢复过程与证据（stop/start 输出、新 daemon 日志、local 消费者活跃确认）
- 验收 4 补测过程与证据（INSERT → fb_post 任务 → fb_contacts → wa_check 入队观察）
- ledger 追加内容

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径

工作目录：/Volumes/DataDrive/proj/public/1699
