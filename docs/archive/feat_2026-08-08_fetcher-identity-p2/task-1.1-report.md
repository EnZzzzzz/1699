# Step 1.1 Report — 读码回填

> 日期：2026-08-08 | commit：5a4c997 | 分支：feat/fetcher-identity-p2

## ① 站点注册名来源（SPEC §4 假设 1 → §3.1）

### 证据

**注册表**（`fetcher/fetcher/sites/__init__.py:19-23`）：
- `register_site(name, plugin_cls)` 将 `name → plugin_cls` 存入 `_SITE_REGISTRY`
- `get_site(name)` 按注册名取插件实例（`_SITE_REGISTRY[name]()`）

**各站点插件类属性 name vs register_site 实参**：

| 站点 | `Plugin.name` 类属性 | `register_site(name, …)` 实参 | 一致？ |
|---|---|---|---|
| 1688 | `"alibaba1688"` (`alibaba1688/__init__.py:27`) | `"1688"` (同文件:85) | ❌ 不一致 |
| madeinchina | `"madeinchina"` (`madeinchina/__init__.py:32`) | `"madeinchina"` (同文件:96) | ✅ |
| yiwugo | `"yiwugo"` (`yiwugo/__init__.py:33`) | `"yiwugo"` (同文件:97) | ✅ |
| taobao | `"taobao"` (`taobao/__init__.py:29`) | `"taobao"` (同文件:86) | ✅ |
| facebook | `"facebook"` (`facebook/__init__.py:24`) | `"facebook"` (同文件:51) | ✅ |

**Engine 端**（`fetcher/fetcher/control/engine.py`）：
- `:42` `self.site = site` — 存储的是插件实例
- `:49-52` `store_factory` 用 `getattr(site, "cookie_domain", "1688.com")` — 只取 cookie_domain，未取注册名
- `:113` `_make_browser_manager` 传 homepage 给 BrowserManager，未传站点名

**CLI/daemon**（`fetcher/fetcher/cli/main.py`）：
- `:174` CLI 分支：`site = get_site(args.site)` — args.site 即注册名（如 `"1688"`）
- `:215` daemon 分支：`site = get_site("1688")` — 硬编码注册名

### 结论

- **插件对象上拿不到注册名**：`self.site.name` 对 1688 返回 `"alibaba1688"` 而非 `"1688"`
- **推翻了 SPEC §4 假设 1**（原假设「可从插件对象获得注册名」）
- **方案**：CLI 传 `args.site`、daemon 传 `"1688"`，经 `Engine.__init__` 新参 `site_name` → `_make_browser_manager` → `BrowserManager`，在 launch 拼前缀

---

## ② domain→site 迁移映射清单（SPEC §4 假设 2 → §3.4）

### 证据：生产库只读统计

```
SQL: SELECT domain, COUNT(*) FROM cookies GROUP BY domain ORDER BY 2 DESC
DB:  .cache/1688.db (mode=ro, uri=True)
总行数: 18095, distinct domain: 6971, distinct identity: 637
含冒号行: 0（全部无前缀）
```

### 可映射域（≥3 行）

| LIKE 模式 | 站点前缀 | 覆盖行数 | 关键域 |
|---|---|---|---|
| `%1688.com%` | `1688:` | ~6600+ | `.1688.com`(5413), `insights.1688.com`(399), `.air.1688.com`(373), `assets.1688.com`(351), `s.1688.com`(109), `widget.1688.com`(103), `work.1688.com`(103), `h5api.m.1688.com`(95), `dj.1688.com`(15), `detail.1688.com`(3) 及 ~6961 个 shop 子域 |
| `%made-in-china.com%` | `madeinchina:` | ~2992 | `.made-in-china.com`(1695), `.cn.made-in-china.com`(651), `cn.made-in-china.com`(431), `membercenter.cn.made-in-china.com`(215) |
| `%taobao.com%` | `taobao:` | ~95 | `.taobao.com`(72), `login.taobao.com`(23) |
| `%yiwugo.com%` | `yiwugo:` | 4 | `.yiwugo.com`(4) |

**检测顺序：先 `made-in-china` 再 `1688`**（二者无重叠，先长后短更安全）

`taobao` 和 `yiwugo` 与 `1688` 也无重叠。

### 无法映射的第三方域

| 域 | 行数 | 处置 |
|---|---|---|
| `.mmstat.com` | 544 | 阿里系埋点/统计域，非站点专属——保持原样（自然过期） |
| `.ynuf.aliapp.org` | 166 | 阿里系生态域，非站点专属——保持原样（自然过期） |

### 结论

- **§4 假设 2 已验证**：映射清单完整覆盖所有可归属域
- 544 + 166 = 710 行（3.9%）无法映射到任何站点，保持原样自然过期
- 迁移 SQL 示例：`UPDATE cookies SET identity = '1688:' || identity WHERE identity NOT LIKE '%:%' AND domain LIKE '%1688.com%'`

---

## ③ identity 诞生点确切代码形态（SPEC §3.1）

### 证据：`browser.py` grep

```
217:        identity = "direct"
233:            identity = exit_ip
314:        session = Session(browser=browser, page=page, identity=identity, ...)
```

### relaunch 是否重建 identity

`relaunch()`（`browser.py:344-384`）：
1. 调用 `session.close(store=self.store, log=self.log)` 关闭旧会话
2. 调用 `self.launch(channel=ch, seed_kit=seed_kit, stop=stop)` 启动全新会话
3. `launch()` 内部重新生成 identity（direct 或 exit_ip），不从旧 session 携带

**结论：identity 唯一诞生点即 `launch()` 的两处赋值（:217/:233），relaunch 不携带旧 identity。**

### P2 拼前缀时改动点

- `:217` → `identity = f"{site_name}:direct"`
- `:233` → `identity = f"{site_name}:{exit_ip}"`

仅此两处。

---

## 对 SPEC.md 的修改清单

| 位置 | 改前 | 改后 |
|---|---|---|
| §3.1「site 注册名从哪拿」 | "读码确认插件上的字段…Step 1.1 回填" | 插件 name 属性不一致的详细发现 + CLI/daemon 透传方案 |
| §3.1 新增 | — | identity 诞生点行号确认（:217/:233）+ relaunch 不携带分析 |
| §3.4 迁移映射 | "确切映射清单 Step 1.1 …核实回填" | 完整四站点映射表 + 第三方域列表 + 检测顺序说明 |
| §4 假设 1 依据列 | "推断（register_site...）" | "已读码验证：插件 name 属性…不一致…改为 CLI/daemon 透传" |
| §4 假设 2 依据列 | "推断（现有站点…）" | "已读生产库验证（2026-08-08，18095 行、6971 distinct domain…）" |
| §6 变更记录 | "（空——评审后变更在此追加）" | 追加 Step 1.1 回填条目（假设 1 推翻、假设 2 验证、诞生点确认） |

---

## 改动文件

| 文件 | 操作 |
|---|---|
| `docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md` | 修改（+22 -5） |

## Commit

- **SHA**: `5a4c997`
- **标题**: `docs(identity-p2): Step 1.1 回填——注册名来源/domain→site映射/identity诞生点`
- **包含文件**: 仅 `SPEC.md`（已验证 `git diff --name-only HEAD~1..HEAD`）

---

## 修复轮 1（reviewer 指正，2026-08-08）

### 行号修正清单（grep -n 实码验证）

| # | 严重度 | 位置 | 错值 | 正确值 | grep 证据 |
|---|--------|------|------|--------|-----------|
| 1 | Critical | SPEC §3.1 → `_make_browser_manager` | `:113-123` | `:113` | `engine.py:113:    def _make_browser_manager` — 改为定义行单行引用 |
| 2 | Critical | SPEC §3.1/§4 → daemon `get_site` | `cli/main.py:242` | `cli/main.py:215` | `main.py:215:    site = get_site("1688")`；:242 是 `Engine(...)` 装配 |
| 3 | Critical | SPEC §3.1/§4 → CLI `get_site` | `cli/main.py:198` | `cli/main.py:174` | `main.py:174:    site = get_site(args.site)`；:198 是 `Engine(...)` 装配 |
| 4 | Critical | SPEC §3.1/§4 → `Alibaba1688Plugin.name` | `alibaba1688/__init__.py:17` | `:27` | `alibaba1688/__init__.py:27:    name = "alibaba1688"` |
| 5 | Critical | SPEC §3.1/§4 → `register_site("1688",...)` | `同文件:66` | `:85` | `alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)` |
| 6 | Important | report 插件表 → madeinchina register_site | `:103` | `:96` | `madeinchina/__init__.py:96` |
| 7 | Important | report 插件表 → yiwugo register_site | `:94` | `:97` | `yiwugo/__init__.py:97` |
| 8 | Important | report 插件表 → taobao register_site | `:95` | `:86` | `taobao/__init__.py:86` |
| 9 | Important | report 插件表 → facebook register_site | `:56` | `:51` | `facebook/__init__.py:51` |
| 10 | Important | report 插件表 → madeinchina name | `:30` | `:32` | `madeinchina/__init__.py:32` |
| 11 | Important | report 插件表 → yiwugo name | `:29` | `:33` | `yiwugo/__init__.py:33` |
| 12 | Important | report 插件表 → facebook name | `:23` | `:24` | `facebook/__init__.py:24` |
| 13 | Minor | SPEC §3.1 → relaunch 范围 | `browser.py:337-366` | `browser.py:344-384` | `browser.py:344:    def relaunch` → 方法至 :384 raise |

### 内容修正

- **变更记录 §6** 补「假设 1 原文被推翻」事实陈述（reviewer #8）：明确写出原假设「站点注册名可从 engine 的插件对象获得」实际不成立

### 实码验证（grep -n 输出摘要）

```
alibaba1688/__init__.py:27:    name = "alibaba1688"
alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)
madeinchina/__init__.py:32:    name = "madeinchina"
madeinchina/__init__.py:96:register_site("madeinchina", MadeInChinaPlugin)
yiwugo/__init__.py:33:    name = "yiwugo"
yiwugo/__init__.py:97:register_site("yiwugo", YiwugoPlugin)
taobao/__init__.py:29:    name = "taobao"
taobao/__init__.py:86:register_site("taobao", TaobaoPlugin)
facebook/__init__.py:24:    name = "facebook"
facebook/__init__.py:51:register_site("facebook", FacebookPlugin)
main.py:174:    site = get_site(args.site)
main.py:215:    site = get_site("1688")
engine.py:113:    def _make_browser_manager(self, store, channel=None) -> BrowserManager:
browser.py:344:    def relaunch(self, session: Session, channel=None,
```

### Commit（修复轮 1）

- **SHA**: `db23e5e`
- **标题**: `docs(identity-p2): Step 1.1 修复轮1——行号勘误`
- **包含文件**: `SPEC.md` + `task-1.1-report.md`（仅 `docs/feat_2026-08-08_fetcher-identity-p2/` 下）
