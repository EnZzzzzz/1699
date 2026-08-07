# Step 1.1 brief — 确认 item 访问契约（SPEC §4 假设 1、2）

> 来源：PLAN.md Phase 1 Step 1.1。本文本是你的需求唯一来源。

## 内容

1. 通读 `fetcher/fetcher/sites/alibaba1688/contact.py` 中 `fetch / validate / on_success / on_giveup / label / cold_start / after_item`（以及它们调用的辅助函数）对 item（shops 表一行）的**全部访问点**，确认访问形式是 `item["domain"]` 式键访问还是 `item.domain` 式属性访问，逐处列出 file:line 和访问的键名。
2. 在 `fetcher/fetcher/` 全包 grep `isinstance` 中带 Task 类名的判断（如 `isinstance(..., ContactTask)`、`type(task) is` 等），重点看 `control/engine.py`、`control/loop.py`、`control/task.py`、`cli/main.py`，确认 Engine/CrawlLoop/CLI 是否对 task 的具体类型有任何特判。
3. 把结论回填到 SPEC：`docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md` §4 表格中假设 1、2 两行的「依据」列从「推断」改为「已读码验证（附 file:line）」，「验证方式」列补上结论（假设 1：dict 可直接替代 / 需 SimpleNamespace / 需其他适配——明确给出；假设 2：无特判 / 有特判在何处）。

## 背景（为什么做这个）

后续 Step 会用 `DaemonTaskProxy` 包装 ContactTask，`acquire_item` 返回的是 work_items 的 payload dict 而非 sqlite Row。本 Step 就是验证「dict 能否 1:1 替代 Row」和「Engine 是否对 task 类型有特判」这两个假设，结论直接决定 Step 2.1 的 payload 形态。

## 验收

- [ ] SPEC §4 假设 1、2 的「依据」列从「推断」改为「已读码验证」，结论明确无歧义
- [ ] item 全部访问点有完整 file:line 清单（写进你的 report）

## 约束

- 本 Step 只读代码 + 改 SPEC.md 一处表格，**不改任何 fetcher 代码**。
- 发现的访问点清单务必完整（漏一处，Step 2.1 就可能踩坑）。
