# Step 3.4 — 平台冒烟（含 SPEC §6.5 start.sh 改动）

> 这是你的需求唯一来源。PLAN Step 3.4 原文 + SPEC §6.5 精确规格抄录如下。

## PLAN Step 3.4 原文（验收以 checkbox 为准）

- [ ] 重启后端（uvicorn 不自动 reload，按 start.sh/stop.sh）；起 daemon 全量
- [ ] API 创建 fb_discover（默认矩阵 × 1 页）→ 断言 work_items 5 条
      （requires=["local"]、engine="ddg"）；创建 fb_group → 断言入队数（fb_groups
      有 pending 时）或 0（空表防御）
- [ ] 冒烟记录写入 ledger.md
- 预估 20min；验收：两类型任务可创建/启动/停止，入队断言正确

## SPEC §6.5 运维：platform/start.sh（本 Step 并入，协调者裁定——PLAN 无独立 Step）

在 daemon 启动前追加（pass-through 幂等）：

```bash
# FB 群采集第三方 API key（fb_group 批次用；缺失时该群采集 FATAL → 批次 failed）
export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"
export APIFY_TOKEN="${APIFY_TOKEN:-}"
```

注释注明：key 由部署方在启动 shell 环境提供（`.env` 已 gitignore，不入库）；
daemon 继承该环境（start.sh 的 nohup 子进程天然继承）。**缺失时原子 FATAL 是既有
行为，本期不新增凭证体系。**

**位置**：追加在既有 `export WA_CHECK_ACCOUNTS=...` 行之后（daemon 启动前）。
**合并而非覆盖**：start.sh 已有 daemon-headed-queues 工作线的改动（--headed 强制 +
WA_CHECK_ACCOUNTS，已 commit dbab0da），本次是追加，不改既有行。

## 环境事实（协调者已验证）

1. **后端 uvicorn 不自动 reload**：改后端代码后必须重启才生效。用 start.sh/stop.sh。
2. **daemon 全局有头**：start.sh 的 DAEMON_ARGS 含 --headed（桌面弹浏览器窗口，勿当
   异常）。本冒烟会起全量 daemon（含新队列 discover_fb/crawl_fb_group，均 local
   消费者，不弹窗）。**注意生产 daemon 34402 已在运行**（feat/facebook-daemon-
   integration 工作线启动的）——先查它是否仍在，若在则冒烟复用（它的代码已是
   最新？不确定——**保守做法：冒烟前用 stop.sh 停掉旧 daemon，重启起新的**，否则
   旧 daemon 进程不认新队列）。
3. **API 地址**：http://127.0.0.1:8765（FastAPI，docs 在 /docs）。创建任务
   POST /api/tasks {"type":"fb_discover","params":{...}}。
4. **默认矩阵**（SPEC §7.4，5 词）：fb_discover 默认 keywords 5 行 × pages 1 = 5
   work_items。若 keywords 传默认矩阵，断言 5 条；若传自定义（如 2 词），断言 2 条
   并注明。
5. **fb_group 断言**：临时/生产库 fb_groups 有 pending 群时才入队；本机无真实
   fb_groups 数据（Step 1.5 冒烟用临时库）→ **预期断言 0 或手工 INSERT 1 条
   pending 群再断言 1**。生产库操作谨慎——若生产库 fb_groups 为空，直接断言 0
   （空表防御路径）。

## 冒烟步骤（建议）

1. **start.sh 改动**（本 Step 的第一个交付）：按 SPEC §6.5 追加两行 export（位置见上）。
   TDD 不适用（shell 配置），但改动要小且精确；无测试，冒烟验证「daemon 日志无
   key 相关报错」+ grep start.sh 断言存在。
2. **重启**：`platform/stop.sh`（停旧的）→ `platform/start.sh`（起新的后端 + 前端 +
   daemon）。确认 daemon 日志出现新队列 discover_fb / crawl_fb_group 注册（
   `[daemon] 队列 discover_fb` 等）。
3. **创建 fb_discover 任务**：POST /api/tasks {"type":"fb_discover","params":
   {"keywords":"site:facebook.com/groups 外贸 whatsapp\nsite:facebook.com/groups 跨境电商 whatsapp",
   "pages":1}} → 断言返回 201 + 任务 id。
4. **断言 work_items**：查库（生产库 .cache/1688.db 只读连接）：
   `SELECT queue, site, batch_id, requires, json_extract(payload_json,'$.engine'),
   json_extract(payload_json,'$.query'), json_extract(payload_json,'$.page')
   FROM work_items WHERE batch_id=<任务id> AND queue='discover_fb'` → 断言 2 条、
   requires='["local"]'、engine='ddg'、query 逐词正确、page=1。**用只读连接**
   （sqlite3.connect('file:...?mode=ro', uri=True) 或 fetcher app.db.connect() 模式）
   ——爬虫可能正在写库。
5. **创建 fb_group 任务**：POST /api/tasks {"type":"fb_group","params":
   {"provider":"brightdata","posts_per_group":50}} → 断言 201。查 work_items
   queue='crawl_fb_group' batch_id=<任务id>：fb_groups 空表 → 0 条（防御路径）。
   可选：手工 INSERT 1 条 pending fb_groups 再创建 → 断言 1 条 + payload
   {"url","provider":"brightdata","limit":50} + 源行 in_progress（若做，冒烟后
   清理该行——这是生产库！）。
6. **启动/停止验证**：POST /api/tasks/<id>/start → 任务 running；POST
   /api/tasks/<id>/stop → 停止（fb_discover 的 2 条 item 会 stopped 或跑完）。
   验证任务终态流转正常。
7. **冒烟记录**追加到 ledger.md（结果 + 命令输出 + 断言）。

## 冒烟记录要求（追加到 ledger.md）

```
## Step 3.4 平台冒烟记录（<日期时间>）
- start.sh：<追加的两行 + grep 证据>
- 后端/daemon：<pid>，新队列注册日志 <片段>
- fb_discover 任务 <id>：work_items <n> 条（requires/engine/query/page 断言）
- fb_group 任务 <id>：入队 <n> 条（空表防御或手动种子）
- start/stop 流转：<观测>
- 验收判定：<满足/不满足>
```

## 你的工作

1. 按上述步骤执行（命令输出全程保留在 report）。
2. 验证验收标准（两类型任务可创建/启动/停止，入队断言正确）。
3. **start.sh 改动需要 commit**（feat commit：`platform/start.sh` +
   ledger.md 冒烟记录 + report/brief）；**严禁 git add -A**。发现代码 bug →
   BLOCKED 上报（不自己修）。
4. 完整证据写入 report。

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.4-report.md`：
- 执行过程与命令输出（start.sh 改动、重启、API 调用、DB 断言）
- **验收证据**：work_items 查询结果（真实行+字段）、任务状态流转、daemon 日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
