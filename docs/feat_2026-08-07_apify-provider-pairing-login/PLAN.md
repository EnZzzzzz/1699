# PLAN — Providers 支持 Apify 供应商 + WhatsApp 配对码登录

> 日期：2026-08-07 · SPEC：同目录 SPEC.md · 状态：待评审

## Phase 清单

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 | 后端：providers 支持 apify kind + migrate 补建表 | 2 | 无 | pending |
| P2 | 后端 + Node：配对码登录链路 | 3 | 无（与 P1 并行可行） | pending |
| P3 | 前端：Providers 页 Apify 形态 | 2 | P1 | pending |
| P4 | 前端：配对码登录 UI | 2 | P2 | pending |
| P5 | 端到端冒烟与验收 | 1 | P1-P4 | pending |

---

## P1 后端：providers 支持 apify kind

**准入**：无。**完成标准**：apify provider 可经 API upsert/读取；config-schema 按 kind 出模板；新库 migrate 后 providers/proxy_channels 表存在；青果回归测试通过。

### P1-S1 config-schema 按 kind 出模板（~10min）
- 文件：`platform/server/app/api/providers.py`
- 内容：加 `_APIFY_CONFIG_TEMPLATE = {"api_token": ""}`；`GET /config-schema` 接受 `?kind=`（缺省 `qingguo`，向后兼容）；kind 不在模板表 → 422。
- TDD：先写失败测试（pytest，apify 模板返回、缺省兼容、未知 kind 422）。
- 验收：
  - [ ] `GET /api/providers/config-schema?kind=apify` 返回含 `api_token` 键
  - [ ] 不带 kind 返回 qingguo 模板（兼容）
  - [ ] `kind=foo` 返回 422
  - [ ] pytest 新增用例通过

### P1-S2 migrate() 补 providers/proxy_channels 建表 + apify 往返测试（~10min）
- 文件：`platform/server/app/db.py`、测试文件
- 内容：`migrate()` 追加两张表 `CREATE TABLE IF NOT EXISTS`（schema 与现库一致）；测试：临时库 migrate 后表存在；`upsert_provider(kind='apify', config={'api_token':'x'})` → `refresh_channels` 无通道无报错；青果 provider 路径回归。
- 验收：
  - [ ] 全新空库 migrate 后两张表存在且与现库 schema 一致
  - [ ] apify provider upsert → GET 读回 config 正确、channels 为空
  - [ ] 现有后端测试全绿

## P2 后端 + Node：配对码登录链路

**准入**：无。**完成标准**：`POST /api/wa/accounts {name, method:"pairing", phone}` 能启动登录进程并产出配对码；登录状态接口返回 `method`/`pairing_code`；qr 方式回归不变。

### P2-S1 check.js 支持 --pairing（~15min）
- 文件：`fetcher/vendor/wa-check/check.js`
- 内容：`collectNumbers` 放行 `--pairing=` flag；`resolvePairing(argv)` 解析号码；`connectWithRetry` 分叉——pairing 模式下每个新 sock 在 `!state.creds.registered` 时调 `requestPairingCode(phone)`，stdout 打印 `PAIRING_CODE: XXXXXXXX` 并落盘 `pairing<suffix>.txt`（suffix 规则复用 qr 文件的，check.js:76-79）。
- 验收：
  - [ ] `node check.js --auth=test --pairing=8613800138000 <占位号>` 运行后 stdout 含 `PAIRING_CODE:` 行且 `pairing-auth_info-test.txt` 落盘，码为 8 字符
  - [ ] 不带 --pairing 时走原 QR 分支（qr.png 落盘，回归）
  - [ ] `node --check check.js` 语法通过

### P2-S2 wa_login.py 支持 method/phone（~15min）
- 文件：`platform/server/app/wa_login.py`
- 内容：`start_login(name, method='qr', phone=None)`：pairing 时校验 `^\d{8,15}$`（不满足抛 ValueError）、启动前删旧 pairing 码文件、cmd 拼 `--pairing=`；`get_state`/login_status 返回 `method` 与 `pairing_code`（读文件，无则 None）；`delete_account` 清理 pairing 文件。
- TDD：mock Popen 的单测覆盖：参数校验、cmd 拼接、pairing_code 读取、delete 清理。
- 验收：
  - [ ] 单测全绿（含 qr 回归）
  - [ ] `start_login('t1','pairing','8613800138000')` 后 get_state 含 method=pairing
  - [ ] 非法手机号（带 +、少于 8 位）→ ValueError

### P2-S3 api/wa.py 接口扩展（~10min）
- 文件：`platform/server/app/api/wa.py`
- 内容：`LoginStartBody` 加 `method: Literal["qr","pairing"]="qr"`、`phone: str|None=None`；pairing 无 phone → 422；透传 wa_login；login 状态响应加 `method`、`pairing_code`。
- 验收：
  - [ ] POST pairing 无 phone → 422；非法 phone → 422
  - [ ] GET login 响应含两个新字段（qr 方式 pairing_code 为 null）
  - [ ] 后端测试全绿

## P3 前端：Providers 页 Apify 形态

**准入**：P1 完成。**完成标准**：页面上能新增/编辑 apify 供应商；非代理类卡片无通道 UI；`npx tsc -b` 通过；页面运行时冒烟通过。

### P3-S1 api.ts + ProviderFormDialog（~15min）
- 文件：`platform/web/src/lib/api.ts`、`platform/web/src/pages/providers/ProviderFormDialog.tsx`
- 内容：`providerConfigSchema` 加 kind 参数；类型 Select 加 `apify（WhatsApp 查号 API）`；选中 apify 且 config 为空时预填 `api_token` 空行。
- 验收：
  - [ ] 新建对话框选 apify → 预填 api_token 行、schema 提示正确
  - [ ] 保存后列表出现 apify 卡片；编辑回显 token；启停开关正常
  - [ ] `npx tsc -b` 通过

### P3-S2 ProviderCard 非代理形态（~10min）
- 文件：`platform/web/src/pages/Providers.tsx`
- 内容：`PROXY_KINDS = new Set(['qingguo'])`；非代理类隐藏通道按钮与 ChannelTable，展示 config 键列表（值打码 `前4位****`）。
- 验收：
  - [ ] apify 卡片无「探测全部通道/同步通道」按钮、无通道表，显示 api_token 打码摘要
  - [ ] 青果卡片 UI 零变化（对照截图）
  - [ ] 运行时冒烟：`/providers` 两 Tab 渲染正常

## P4 前端：配对码登录 UI

**准入**：P2 完成。**完成标准**：添加账号可选配对码方式，对话框展示配对码并可完成登录轮询；qr 方式回归；`npx tsc -b` 通过。

### P4-S1 api.ts + AddAccountDialog（~15min）
- 文件：`platform/web/src/lib/api.ts`、`platform/web/src/pages/wa/AddAccountDialog.tsx`、`platform/web/src/pages/WaAccounts.tsx`（仅透传 method）
- 内容：类型 `WaLoginStatus` 加 `method`、`pairing_code: string|null`；`createWaAccount(name, method, phone?)`；对话框加方式切换（扫码默认/配对码）+ 手机号 Input（配对码时必填，前端同 `^\d{8,15}$` 校验）；创建成功后把 method 传给登录对话框。
- 验收：
  - [ ] 选配对码未填手机号 → 表单报错不提交
  - [ ] `npx tsc -b` 通过

### P4-S2 ScanLoginDialog 双模式（~15min）
- 文件：`platform/web/src/pages/wa/ScanLoginDialog.tsx`
- 内容：加 prop `method`；pairing 模式按 SPEC §2.4 渲染配对码（等宽大号、`XXXX-XXXX`、Skeleton 占位、无刷新倒计时、重试按钮文案「重新获取配对码」）；qr 模式零变化。
- 验收：
  - [ ] pairing 模式轮询到码后正确展示；connected/failed/expired 终态逻辑复用正常
  - [ ] qr 模式与现状逐像素一致（对照截图）
  - [ ] `npx tsc -b` 通过；页面运行时冒烟

## P5 端到端冒烟与验收

**准入**：P1-P4 完成。**完成标准**：真实环境全链路走通。

### P5-S1 运行时冒烟（~15min，需重启后端 + 用户配合一次）
- 内容：重启 uvicorn；前端 dev 跑起来。
  - [ ] API 创建 apify provider（真实 token），页面可见、编辑/启停正常
  - [ ] qr 方式登录流程回归（发起登录出二维码即可，不必真扫）
  - [ ] pairing 方式发起登录，配对码真实产出并展示（**由用户决定是否真拿手机完成一次配对验证**——不阻塞交付，真机验证结果记录在 ledger）
  - [ ] `npx tsc -b` + 前后端测试全绿
  - [ ] AGENTS.md 无需更新（确认无约定变化）

---

## 冲突扫描记录（评审前已做）

1. **PLAN 内部**：P2-S2 的「启动前删旧 pairing 文件」与 P2-S1 的落盘契约互斥检查——删除只发生在 start_login，不影响运行中进程写文件，无矛盾。P3-S2 的 `PROXY_KINDS` 判定与未来新增代理类型需同步维护，已在 SPEC 写明集合位置。
2. **PLAN vs 代码库现状**：
   - `config-schema` 加 `?kind=` 缺省 qingguo，现有前端调用（api.ts:317 无参）不受影响；P3-S1 负责迁移为显式传 kind。
   - `POST /api/wa/accounts` 加可选字段向后兼容；现有前端 `createWaAccount(name)` 调用在 P4-S1 才改签名，期间旧调用仍合法（method 缺省 qr）。
   - `WaLoginStatus` 加字段为增量，现有 ScanLoginDialog 不读新字段，P4-S2 前不破坏。
   - `_sessions` 内存态重启失效为现状，pairing 码文件在重启后仍可读——get_state 对未知 name 的兜底逻辑沿用现状，不加新分支。
3. **PLAN vs 外部依赖**：`requestPairingCode` 存在性已核实（node_modules 7.0.0-rc14 源码 socket.js:596-606 + 官方 README），无需 spike。Baileys  pairing 成功率受 WhatsApp 风控影响（新设备/新号可能被拒发码）——属外部不可控，验收以「码正确产出或 Baileys 明确报错透出」为准。
