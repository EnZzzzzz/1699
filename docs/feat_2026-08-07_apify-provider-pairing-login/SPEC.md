# SPEC — Providers 支持 Apify 供应商 + WhatsApp 配对码登录

> 日期：2026-08-07 · 状态：待评审

## 1. 背景与目标

### 1.1 背景

- wa_check 查号目前只有 Baileys 协议自查一条路：用自己的小号扫码登录（`fetcher/vendor/wa-check/auth_info*/`），批量查号极易封号。
- 已实测 Apify actor `devscrapper/whatsapp-number-validator` 可替代查号（REST API、$0.004/号、准确率 29/30 与 Baileys 一致），token 已拿到。
- 平台的 `/providers` 页面目前只支持青果代理一种 `kind`，无法登记 Apify 这类 API 凭证供应商。
- 登录 Baileys 账号只支持扫码；有些场景（手机不在身边、远程服务器）用「手机号 + 配对码」更方便，Baileys v7 原生支持 `requestPairingCode`。

### 1.2 目标（两个独立小特性，同一批交付）

**F1. Providers 页支持 Apify 供应商**
- 能在 `/providers` 页面新增/编辑/启停 `kind='apify'` 的供应商，config 存 `api_token`。
- 卡片展示适配非代理类供应商（无通道概念时不显示通道相关 UI）。

**F2. WhatsApp 账号支持配对码登录**
- 添加 WhatsApp 账号时可选「扫码」或「配对码」两种方式；配对码方式输入手机号（带国家码纯数字），界面展示 8 位配对码，用户在手机 WhatsApp「已链接的设备 → 关联设备 → 改用电话号码」输入完成登录。
- 登录产物（`auth_info-<name>/` 会话目录）与扫码方式完全一致，下游（wa_check 原子、wa_tasks、任务表单）零改动。

### 1.3 非目标（明确不做）

- **不做** wa_check 消费 Apify token 的执行链路（新 atom / wa_tasks provider 分支 / 任务表单选择查号渠道）。本次只把凭证登记进 providers 表；消费链路是下一个 feature。
- 不做 providers 表凭证加密（现状明文，沿用）。
- 不改 wa_tasks.py、runner.py、atoms/wa_check.py、TaskFormDialog.tsx。
- 不做登录进程硬超时重构（沿用 SCAN_TIMEOUT 语义）。

## 2. 契约与行为后果

### 2.1 providers 表与后端

- 表结构（现状，`.cache/1688.db`）：`providers(id, kind, name, config_json, enabled, created_at, updated_at)`。`kind` 后端**无校验**（`api/providers.py:42` 默认 `'qingguo'`，自由文本），`config_json` 自由 JSON 明文。
- `refresh_channels`（`proxy_ops.py:140`）对 config 中无 `tunnels/servers` 的供应商同步出 0 条通道，**对 Apify 天然无害**（已读码确认 `proxy_ops._resolve_tunnels:125` 只在 kind==qingguo 时有特殊回退）。
- `/api/providers/config-schema` 目前硬编码 qingguo 模板（`api/providers.py:102-127`）。改为接受 `?kind=` 查询参数：`qingguo`（默认，保持兼容）返回现有模板，`apify` 返回 `{"api_token": ""}`。模板值出参前走现有 `_mask()`（providers.py:77-85），空值无碍。
- `providers` / `proxy_channels` 建表不在 `db.migrate()`（`db.py:17-45`），是历史手工建表。本次把两张表的 `CREATE TABLE IF NOT EXISTS` 补进 `migrate()`，幂等，对现有库无影响。

**行为假设与依据**：
- 「新增 kind=apify 不破坏现有代理池逻辑」：依据 = 已读码（`proxy_ops.py` 全部分支只对 kind==qingguo 特判）。验证方式 = 后端单测：upsert 一个 apify provider 后调 `refresh_channels`，断言不产生通道、不报错；青果 provider 行为回归不变。
- 「前端通用键值对表单可直接承载 api_token」：依据 = 已读码（`ProviderFormDialog.tsx:148-193` config 为动态键值行）。验证方式 = 前端运行时冒烟。

### 2.2 Baileys pairing code

- 版本：`@whiskeysockets/baileys` 实际安装 **7.0.0-rc14**（node_modules 实测）。
- API：`sock.requestPairingCode(phoneNumber)` 返回 **8 字符 Crockford base32 无连字符**（lib/Socket/socket.js:596-606）；`XXXX-XXXX` 仅展示习惯，前端自行插连字符。
- 调用条件（官方 README:209-230）：号码为**带国家码纯数字**；必须在 `!sock.authState.creds.registered` 时、`makeWASocket` 之后尽早调用；`printQRInTerminal: false`（check.js 已是）。依据 = 官方 README + 库源码，非推断。
- pairing 模式不会触发 `connection.update` 的 `qr` 分支；等待用户输码期间连接保持 pending；pairing 成功后同样走 `connection === 'open'` → check.js 打印「已连接，开始查询...」——**登录完成判定与 Python 侧状态机完全复用，零改动**。
- 配对码一次性、短时效（官方未给明确时长，经验值几分钟内）。过期/失败后用户点「重新获取配对码」重发登录请求（复用现有 retry 按钮逻辑）。
- 「已登录 409 守卫」（`wa_login.py:100-104`）天然保证 pairing 调用时 `!registered` 成立。

**配对码传递给前端的契约（与 qr.png 同构，文件轮询）**：
- check.js 收到 code 后：① stdout 打印固定格式行 `PAIRING_CODE: XXXXXXXX`；② 落盘文件 `wa-check/pairing<suffix>.txt`（suffix 规则与 qr 文件一致：默认账号空、命名账号 `-auth_info-<name>`，见 check.js:76-79 同款逻辑）。
- Python 用**读文件**（不用解析 stdout tail 正则）取码：与 qr.png 的 `FileResponse + mtime` 契约最匹配，最稳。
- `delete_account` 同步删除 pairing 码文件（参照 qr 文件清理，wa_login.py:194-211）。

### 2.3 登录 API 与状态机

- `POST /api/wa/accounts` 请求体扩展：`{name, method?: "qr"|"pairing", phone?: string}`。缺省 `method="qr"`，**完全向后兼容**现有前端/调用方。
- `method="pairing"` 时 `phone` 必填，校验：`^\d{8,15}$`（纯数字带国家码，与原子层 `normalize_numbers` 口径一致）；不满足 → 422。
- 登录状态机复用现有四态 `waiting_scan/connected/failed/expired`，**不新增状态**；`GET /api/wa/accounts/{name}/login` 响应增加两个字段：`method`（回显登录方式）、`pairing_code`（string|null，仅 pairing 方式且文件已产出时有值）。
- SCAN_TIMEOUT 300s 语义沿用（wa_login.py:140-142）。

### 2.4 前端交互形态（唯一确定形态，遵守 DESIGN.md）

**F1 Providers 页**：
- `ProviderFormDialog.tsx` 类型 Select 增加选项 `apify（WhatsApp 查号 API）`；选中 apify 时若 config 为空则预填一行 `api_token`（值为空），schema 提示文案调用 `api.providerConfigSchema('apify')`。
- `Providers.tsx` 的 `ProviderCard`：kind 为代理类（现有仅 qingguo，代码里用集合 `PROXY_KINDS = new Set(['qingguo'])` 判定）时保持现状；**非代理类隐藏**「探测全部通道」「同步通道」按钮和 `ChannelTable`，改为展示 config 键列表（值打码：前 4 位 + `****`，仅展示用，编辑表单仍回显明文）。
- 卡片其余部分（启用开关、编辑、类型文本）不变。

**F2 添加账号 + 登录对话框**：
- `AddAccountDialog.tsx`：账号名输入下方加登录方式选择——两个并排 Radio（shadcn RadioGroup，若无该组件则用两个 outline Button 切换态）：「扫码登录」（默认）/「配对码登录」。选配对码时出现手机号 Input（`placeholder="带国家码纯数字，如 8613800138000"`）。提交调 `api.createWaAccount(name, method, phone?)`。
- `ScanLoginDialog.tsx` 扩展为双模式（不新建组件）：通过新增 prop `method` 区分。
  - pairing 模式：标题「配对码登录」；二维码区域替换为等宽大号配对码（`text-3xl font-mono tracking-widest`，`XXXX-XXXX` 展示，轮询到 `pairing_code` 后渲染；未产出前显示 LoadingState 同款 Skeleton）；提示文案「打开手机 WhatsApp → 设置 → 已链接的设备 → 关联设备 → 改用电话号码，输入上方配对码」；**无 60s 刷新倒计时**（配对码不自动刷新）；failed/expired 时按钮文案「重新获取配对码」。
  - qr 模式：现有行为一字不动。
- 颜色/排版/按钮均沿用现有对话框组件与 DESIGN.md token，不新增色值。

## 3. 职责分配（初始化 + 变更路径）

| 数据 | 谁写 | 谁读 | 变更同步 |
|---|---|---|---|
| providers 行（apify） | `POST/PUT /api/providers` → `proxy_ops.upsert_provider/update_provider` | `GET /api/providers` → Providers 页 | 编辑走现有 PUT；`refresh_channels` 对无 tunnels 为 no-op |
| pairing 码文件 | check.js（pairing 模式落盘） | wa_login.get_state 读文件 → login 状态接口 → ScanLoginDialog 2s 轮询 | 每次新登录进程启动前 wa_login 先删旧文件（防串码）；delete_account 清理 |
| 登录状态 `_sessions` | wa_login 泵线程/惰性超时 | GET login 接口 | 内存态，重启失效（现状沿用） |
| Baileys 会话 `auth_info-<name>/` | check.js（pairing 或 qr 成功后 `creds.update` 落盘） | api/wa.py 账号发现、wa_check 原子、wa_tasks | 与登录方式无关，现有逻辑 |

## 4. 影响面

- 改：`platform/server/app/api/providers.py`、`platform/server/app/api/wa.py`、`platform/server/app/wa_login.py`、`platform/server/app/db.py`、`fetcher/vendor/wa-check/check.js`、`platform/web/src/pages/providers/ProviderFormDialog.tsx`、`platform/web/src/pages/Providers.tsx`、`platform/web/src/pages/wa/AddAccountDialog.tsx`、`platform/web/src/pages/wa/ScanLoginDialog.tsx`、`platform/web/src/lib/api.ts`。
- 不改：wa_tasks.py、runner.py、atoms/wa_check.py、TaskFormDialog.tsx、WaAccounts.tsx（仅间接受益）。
- 后端改完需重启 uvicorn（AGENTS.md §4）。
