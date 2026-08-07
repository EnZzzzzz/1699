# SDD ledger — plan: docs/feat_2026-08-08_fetcher-identity-p2/PLAN.md

- 分支：feat/fetcher-identity-p2（base main 83120db，main 已含 P0+P1）
- 环境记录：子 Agent 经 `pi -p --model <model>` 独立进程派发（经济=deepseek/deepseek-v4-flash，标准=deepseek/deepseek-v4-pro，终审=deepseek/deepseek-v4-pro）；会话 --session-id 固定便于修复轮 resume；制品全部文件交接（plan 目录）。
- 仓库注意：工作区有另一功能（apify-provider-pairing-login）的未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**P2 全程不碰不提交**，commit 一律 scoped add。

## Step 进度

- Step 1.1: complete (commits cfdca75..5f8764e, review clean)
  - 关键产出：注册名来源结论——插件 name 属性不可用（1688 的 plugin.name='alibaba1688' ≠ 注册名 '1688'），改为 CLI/daemon 透传 site_name；§4 假设 1 被推翻（变更记录已记）；domain→site 映射清单（%1688.com%→1688:、%made-in-china.com%→madeinchina:、%taobao.com%→taobao:、%yiwugo.com%→yiwugo:，先 made-in-china 再 1688）；无法映射第三方域 .mmstat.com(544)/.ynuf.aliapp.org(166) 保持原样；identity 诞生点 browser.py:217/:233，relaunch 不携带旧 identity
  - 首次 review 8 条发现（4C/2I/2M）全是行号错误（implementer 行号系统性偏差），修复轮 1 全部 ADDRESSED；已用 grep -n 逐条实码复核
  - Step 1.1: minor (deferred): browser.py relaunch 范围 :344-384 的右端点 :384 是空白行，方法体实际 :381（文档引用精度，P3 编码阶段可精确化）
