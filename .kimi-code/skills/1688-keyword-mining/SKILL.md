---
name: 1688-keyword-mining
description: 从 1688 国际站（阿里巴巴国际站 alibaba.com）提取类目名、商品标题、商品链接等语料，候选关键词去重后直接追加进 FB/X 词库（靠词库日落机制自动淘汰差词，不做人工验证），同时所有看到的类目与商品语料写入 SQLite 语料表。当用户说"挖词"、"提取关键词"、"从 1688 找关键词"、"扩词库"时使用。
---

# 1688 关键词挖掘 + 语料入库

从阿里巴巴国际站（alibaba.com，即"1688 国际站"官网）提取类目/商品语料 → 候选词去重后追加 FB/X 词库 → 所有看到的类目与商品写入语料表。

**2026-08-22 用户拍板：不做 X/FB 人工验证**。词库有日落机制（`kw_stats` 连续无新号自动退役），差词会被自动淘汰，省掉逐词验证的浏览器操作与封号风险。

## 频率控制（防风控，全程适用）

操作的是用户真实登录态的浏览器：

- **单站连续操作 ≤ 15 分钟，按站点独立计时**（2026-08-22 用户明确）：alibaba、X、FB 各算各的窗口，互不占额度。到点停手汇报进度，等用户说继续再开该站下一个窗口。
- **每次页面跳转间隔 5~15 秒随机等待**（bash `sleep $((5 + RANDOM % 11))`），禁止连续秒开页面。
- 遇到验证码/限流页/账号异常提示：**立即停手并告知用户**，不要尝试绕过。

## 交互方式铁律（用户指定，2026-08-22）

**禁止在 URL 里手工拼接关键词**（不拼 `?q=xxx` 直链）。搜索一律：navigate 首页 → snapshot 找搜索框 → fill 输入 → 提交（点按钮或回车）。点站方自己渲染的类目/商品链接不算拼接，直接用其 href 导航即可。

X 的已知坑（2026-08-22 实测）：搜索框回车的合成键盘事件不生效，要点输入后**点下拉联想第一项 `Search for "..."`（用 WebBridge `click` 工具点 @e ref，别用 dispatchEvent）**才能进结果页；`Latest` 标签同理用 click 工具。

## 第 0 步：前置准备

1. **提醒用户登录 1688 国际站（alibaba.com）**；不再强制 X/FB 登录（已不做验证）。
2. **加载 `kimi-webbridge` skill**，所有浏览器操作走 WebBridge。
3. **读项目根 `AGENTS.md` §1/§4**：词库追加规范（`grep -qxF`，禁止 `sort -u`）与数据库约定（北京时间字符串、短事务、`busy_timeout=30000`）。

## 第 1 步：提取（alibaba.com）

入口：`https://www.alibaba.com/` 首页类目导航、类目索引页（如首页「Browse featured selections」指向的 all-categories 页），或用户指定类目页。首页是重 JS 站且可能中文本地化，`navigate` 后 `sleep 6~10` 再抓；若为中文，先让用户手动切英文（语言选择器的合成点击不一定生效）。

抓三类信息，`evaluate` 一把抓：

1. **一级类目名**（`h1/h2/h3` 或类目导航项）；
2. **二三级类目名**（类目索引页的链接文本）；
3. **商品标题 + 链接**（类目页/列表页的商品卡片：标题文本 + `<a>` 的 href）——**商品标题是后期重要语料，必须连同链接一起抓全**。

```js
// 类目/链接一把抓
[...document.querySelectorAll('a')].map(a => ({t: a.textContent.trim(), h: a.href}))
  .filter(x => x.t.length > 2 && x.t.length < 200)
// 商品标题（列表页，按实际 DOM 微调选择器）
[...document.querySelectorAll('[class*=title], [class*=subject], h2, h3')].map(e => e.textContent.trim())
```

翻页/滚动加载：列表页向下滚动 2~3 屏再抓一轮，合并去重。

> 已知坑（2026-08-22 实测）：`world.1688.com` 在真实浏览器里也 ERR_TOO_MANY_REDIRECTS，禁用；"1688 国际站"官网就是 alibaba.com（谷歌确认）。备用类目源：`https://www.made-in-china.com/products-directory/`。

## 第 2 步：清洗与去重

- 类目词只留**英文**、2~40 字符；去掉界面文案（按钮、帮助链接、促销语）。
- 商品标题**保留原文完整入库**（语料用途，不做裁剪；用户 2026-08-22 明确），只剥首尾角标（"certified"、"Easy Return" 等）。
- **候选关键词有两个来源**：① 类目名原文；② **从商品标题提取高频 2~3 词词组**——清洗规格参数（`\d+\s*(gb|tb|inch|hz|rpm|mah...)`）、促销词（wholesale/factory price/oem/hot sale 等停用词表）后做 n-gram 计数，取频次 ≥2 且可读通顺的词组。注意剥离标题里粘着的卡片角标（"Lower priced than similar"、"Easy Return"、"Reorder rate"、"180-day lowest"，胶水形态如 `returnreorder`、`padeasy`，2026-08-22 实测污染），反向词序片段（如 "system smart home"）和纯规格碎片（gddr/gtx ti 等）也剔除。
- 候选词对照现有词库去重：`.cache/x_keywords_all.txt`、`.cache/fb_keywords_extra.txt`、`scraper/fb_keyword_search.py` 与 `scraper/x_keyword_search.py` 内置词表；已在库的跳过。
- 候选多时先给用户看清单（≤50 个）圈范围，再追加。

## 第 3 步：语料入库（所有看到的都写）

**凡是在页面上看到的类目名、商品标题、链接，全部写入语料表**（不只入选关键词）。表在项目库 `.cache/1688.db`：

```sql
CREATE TABLE IF NOT EXISTS mined_corpus (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL DEFAULT 'alibaba',  -- 来源站点
  kind TEXT NOT NULL,                      -- category1(一级类目)/category(子类目)/product(商品标题)
  title TEXT NOT NULL,                     -- 类目名或商品标题原文
  url TEXT DEFAULT '',                     -- 链接（类目页或商品页）
  category TEXT DEFAULT '',                -- 所属一级类目（商品/子类目用）
  first_seen_at TEXT NOT NULL,             -- 北京时间 YYYY-MM-DD HH:MM:SS
  last_seen_at TEXT NOT NULL,
  UNIQUE(source, kind, title, url)
);
```

- 写入用 python3 + sqlite3，**短事务 + `PRAGMA busy_timeout=30000`**；重复遇到 `ON CONFLICT` 只更新 `last_seen_at`（`INSERT ... ON CONFLICT(source,kind,title,url) DO UPDATE SET last_seen_at=excluded.last_seen_at`）。
- 抓取时把每页结果先存临时 JSON（如 `/tmp/ali_*.json`），最后用脚本批量入库，避免长事务占库。

## 第 4 步：关键词入词库并生效

- X 词：`grep -qxF '<词>' .cache/x_keywords_all.txt || echo '<词>' >> .cache/x_keywords_all.txt`
- FB 词：同理追加 `.cache/fb_keywords_extra.txt`（同一候选词两边都加，不再分平台验证）
- **禁止 `sort -u` 重写词库**。
- 重启对应脚本生效（先杀旧进程再按 AGENTS.md §1 nohup 命令重启）。新词在 state 无 `kw_stats` 即视为到期，重启后下一轮即刺探，无回扫成本；差词由日落机制自动退役。

## 第 5 步：输出汇总

| 项 | 数量 |
|---|---|
| 一级类目（入库） | N |
| 子类目（入库） | N |
| 商品标题+链接（入库） | N |
| 候选关键词（去重后） | N |
| 追加 X 词库 / FB 词库 | a / b |

最后一行结论：本轮浏览了哪些类目页、入库多少条语料、追加哪些词、是否已重启脚本。
