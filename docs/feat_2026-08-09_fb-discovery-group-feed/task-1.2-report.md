# Step 1.2 报告 — FetchDdgSerp 原子 + 纯函数（TDD）

> 日期：2026-08-09 · implementer：subagent · 依据：task-1.2-brief.md（PLAN Step 1.2 + SPEC §5.1 + 协调者裁定）

## 实现了什么

新建 `fetcher/fetcher/atoms/facebook_discover.py`（对齐 facebook_group.py 模式）：

- **`_http_get(url, timeout) -> (status, html)`**（模块级，便于 mock）：
  urllib 裸 GET `https://html.duckduckgo.com/html/`，浏览器 UA（Chrome 125）+ `Accept-Language: zh-CN` + `Accept-Encoding: gzip`；`Content-Encoding: gzip` 时解压。
  传输层异常（`URLError` / `socket.timeout`）原样上抛；`HTTPError`（403/429/5xx 等）返回 `(code, "")` 由原子映射——对齐 `_http_json` 的 catch 模式（裁定 3）。
- **`parse_serp_results(html) -> list[{"url","title"}]`**：正则抽 `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=...&amp;rut=...">` 锚点 → `uddg=` 参数 `unquote` 解码 → 标题去标签 + `html.unescape` + strip。返回全部有机结果不过滤；无锚点/坏 HTML → `[]`。
- **`classify_fb_url(url) -> (kind, group_id, group_url) | None`**：`POST_RE = facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)` → `("post", gid, 派生群主页)`；`GROUP_RE = facebook\.com/groups/([^/]+)` → `("group", gid, 归一化群主页 https://www.facebook.com/groups/{gid})`；视频/用户主页/非 FB → None。group_id 语义 = 群 id（数字或 slug，URL 解析），与 fb_posts/fb_groups 表 `group_id` 列一致。
- **`FetchDdgSerp` 原子 run**：
  - params 校验（裁定 1）：query 缺失/非 str/空白 → FATAL；page < 1（含 0、负数、"0"）→ FATAL；FATAL 不发请求。
  - 节奏：请求后统一 `ctx.wait(uniform(sample_min', sample_max))`，`sample_min' = max(sample_min, MIN_SAMPLE_FLOOR=60)`（模块常量注释写明 spike §8.1 依据）；**202 路径先 `ctx.wait(uniform(180,240))` 再节奏 wait**（2 次 wait，裁定 2）；`ctx.wait` 被中断（返回 True）→ SKIPPED。
  - Outcome 映射：200+结果 → OK（data=`{"engine":"ddg","query","page","results":[{"url","title","kind","group_id","group_url"}...]}`）；200+0 结果 → EMPTY；202/403/429 → BLOCKED；传输错误/5xx/其他非 200 → NET_ERROR；请求前 `ctx.stopped()` → SKIPPED（wait 0 次、不发请求，裁定 2）。
  - 请求 URL：`?q=<urllib.parse.quote(query)>（safe='/'，裁定 5）&s=(page-1)*10`。
  - 非 FB 结果保留在 results 中（kind/group_id/group_url=None），不过滤——对应 SPEC「parse 返回全部有机结果、FB 过滤在下一级纯函数」的语义，分流交给 Step 1.3 任务（SPEC §5.2）。

**fixture（裁定 7）**：不复制大文件，测试直接引用真实 spike 样本 `docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html`（33KB > 20KB 复制上限，改为按路径读入）。

## 测了什么、测试结果

新建 `fetcher/tests/test_facebook_discover.py`，35 个测试，全部通过：

| 测试组 | 覆盖 |
|---|---|
| TestParseSerpResults (5) | 真实样本：10 条结果、url 全解码为 https FB 群 URL、键只有 url/title；首条与样本逐字核对；标题 `&amp;/&lt;` 实体还原；标题去 `<b>` 标签；坏 HTML/空 → [] |
| TestClassifyFbUrl (7) | 帖 permalink（数字群 id）、permalink 变体（slug 群 id）、群主页（数字/slug、去尾部斜杠归一化）、视频 → None、用户主页 → None、非 FB → None |
| TestAtomParams (4) | query 缺失/非 str/空白 → FATAL 且不发请求；page 0/-1/"0" → FATAL |
| TestAtomHttpOutcomes (15) | OK（数据形状/engine/query/page/results、请求 URL 的 q=quote 与 s=offset、wait=1 次且 ≥60）、page 2 → s=10、混合 kind（post/group/None 全保留）、EMPTY（仍 wait 1 次）、202→BLOCKED（wait 2 次，退避 ∈[180,240]+节奏 ≥60）、403/429→BLOCKED、5xx→NET_ERROR、传输异常→NET_ERROR（不 wait）、超时→NET_ERROR、请求前停止→SKIPPED（wait 0、不发请求）、等待中中断→SKIPPED、节奏地板（10/20 → 60.0）、节奏区间（90-120） |
| TestHttpGet (5) | 请求头（UA/Accept-Language/Accept-Encoding/timeout）、gzip 解压、HTTPError→(429,"")、URLError 上抛、socket.timeout 上抛 |

**验收命令**：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"` → 35 通过；回归 `-p "test_facebook*.py"` → 72 通过（37 旧 + 35 新，旧测试不动）；全量 `-p "*.py"` → 697 通过。输出干净（无 error/warning）。

## TDD 证据

**RED**：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"
ImportError: cannot import name 'facebook_discover' from 'fetcher.atoms'
    (…/fetcher/fetcher/atoms/__init__.py)
FAILED (errors=1)
```
失败原因 = 模块不存在（功能缺失），符合预期——测试先行，实现后补。

**GREEN**：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"
Ran 35 tests in 0.003s
OK
```

**TDD 驱动的 2 处实现修正**（测试先失败、改实现转绿）：
1. `page=0`：初版用 `int(params.get("page") or 1)`，`0 or 1` 把显式 0 当成缺省 → OK 而非 FATAL。测试 `test_page_lt_1_is_fatal` 失败暴露 → 改为 `int(raw_page) if raw_page is not None else 1`。
2. 请求头断言：本 Python 版本 `Request.get_header` 大小写敏感直查 dict，而 `add_header` 把 key 首字母大写 → `get_header("Accept-Language")` 返回 None。测试 `test_request_headers` 失败 → 测试改为对 `req.headers` 转小写做不区分大小写断言（实现本身无问题，头确实发出）。

## 改动的文件

- `fetcher/fetcher/atoms/facebook_discover.py`（新建：原子 + 3 个模块级函数 + 常量）
- `fetcher/tests/test_facebook_discover.py`（新建：35 测试）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md`、`task-1.2-report.md`（本 Step 文档）

## 自查发现

- **解释性裁定（非阻塞）**：OK 的 `results` 保留非 FB 条目（kind=None）。依据：SPEC「parse 返回全部有机结果（不过滤）、FB 过滤在下一级纯函数」+ OK data 每结果含 kind 字段；Step 1.3 按 kind 分流时自然跳过 None（SPEC §5.2「帖 permalink 类」「全部 FB 群 URL」两类都不命中 None 行）。若评审倾向过滤，改动点集中在 run 的 results 组装一处。
- **防御性补充（超出字面规格，已注释）**：`sample_max` 低于 60s 地板时抬到地板——SPEC §5.2 规定 task 透传 `ctx.config.sample_min/max`（缺省 13-20s），若不抬，`uniform(60, 20)` 抛 ValueError → 每个查询 NET_ERROR，真实链路必炸。已在代码注释说明。
- **`sample_max` 缺省**：未传时取 `sample_min' + 20`（即 uniform(60,80)），SPEC 未定义缺省值，取了留余量的宽松上界。
- classify 的 group_id = 群 id（URL 解析），与 fb_posts/fb_groups 表 group_id 列语义核对一致（db.py 建表注释「群 id（数字或 slug，URL 解析）」）。
- 未注册 `atoms/__init__.py`（brief 未要求，Step 1.3 直接 `from fetcher.atoms.facebook_discover import FetchDdgSerp` 即可）。

## 问题或疑虑

- 无阻塞问题。上述 3 处解释/防御性细节请评审确认。
- 真实 DDG 抓取未在本次验证（spike 已证 2026-08-09 端点可用；本 Step 全 mock HTTP，符合 brief「不依赖真实网络」）。
