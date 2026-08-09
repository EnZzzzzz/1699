# Step 1.2 — FetchDdgSerp 原子 + 纯函数（TDD）

> 这是你的需求唯一来源。PLAN Step 1.2 原文 + SPEC §5.1 精确规格抄录如下。

## PLAN Step 1.2 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/atoms/facebook_discover.py`：
      `_http_get(url, timeout) -> (status, html)`（urllib + UA + gzip 解压，模块级
      便于 mock）
- [ ] `parse_serp_results(html) -> list[{"url","title"}]`（抽 result__a → uddg 解码
      → 标题净化；真实样本 spike/ddg_sample_1.html 截取 fixture）
- [ ] `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`
      （POST_RE / GROUP_RE 双正则，SPEC §5.1）
- [ ] `FetchDdgSerp` 原子 run：params 校验、节奏（sample floor 60 + 202 退避
      uniform(180,240)）、Outcome 映射（OK/EMPTY/BLOCKED/NET_ERROR/SKIPPED/FATAL）
- [ ] 测试（`fetcher/tests/test_facebook_discover.py`）：parse 样本结构/标题实体、
      classify 各形态（帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、
      202→BLOCKED、停止→SKIPPED、节奏 wait 次数
- 预估 60min；验收：新测试全绿 + `test_facebook.py`/`test_facebook_group.py` 回归
  不动（跑全 fb 测试组）

## SPEC §5.1 FetchDdgSerp 原子（精确规格）

新文件 `fetcher/fetcher/atoms/facebook_discover.py`：

```python
class FetchDdgSerp:
    name = "fetch_ddg_serp"
    title = "DDG抓FB群帖SERP"

    params = {
        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
                             原子强制下限 60，spike 依据见 §8.1）
        "sample_max": float 可选，查询间节奏上限秒
        "timeout":    int   可选，HTTP 超时（缺省 30）
    }
```

- **HTTP**：urllib 裸 GET `https://html.duckduckgo.com/html/?q=<quote(query)>&s=<offset>`，
  浏览器 UA（Chrome 125 同款）+ `Accept-Language: zh-CN` + `Accept-Encoding: gzip`
  （响应 gzip 解压）。模块级 `_http_get(url, timeout) -> (status, html)` 独立成函数，
  单测 monkeypatch 即可覆盖全部 HTTP 路径（对齐 facebook_group.py 的 `_http_json` 模式）。
- **纯函数 `parse_serp_results(html) -> list[{"url","title"}]`**：正则抽
  `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">`
  锚点 → `uddg=` 参数 URL 解码 → 标题去标签/HTML 实体（&amp; 等）。返回**全部**有机
  结果（不过滤），FB 过滤在下一级纯函数。真实样本：spike/ddg_sample_1.html。
- **纯函数 `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`**：
  - `POST_RE = facebook\.com/groups/[^/]+/(?:posts|permalink)/(\d+)` → kind="post"，
    group_url = 派生的群主页 `https://www.facebook.com/groups/{gid}`；
  - `GROUP_RE = facebook\.com/groups/([^/]+)` → kind="group"，group_url = URL 自身
    （归一化到 `https://www.facebook.com/groups/{gid}`，去尾部斜杠）；
  - 其余 URL（FB 视频/用户主页/广告页/非 FB）→ None。
- **节奏**：无论 outcome，请求后 `ctx.wait(random.uniform(sample_min', sample_max))`
  （`sample_min' = max(sample_min, 60)`，模块常量 MIN_SAMPLE_FLOOR 注释写明 spike
  依据）；**HTTP 202（anomaly 限流）时先 `ctx.wait(uniform(180, 240))` 再返回
  BLOCKED**（覆盖 spike 实测封禁窗口，§8.1）。
- **Outcome 口径**（对齐 FetchFbGroupPosts）：
  - 200 + results → **OK**，`data={"engine":"ddg","query","page","results":[
    {"url","title","kind","group_id","group_url"}...]}`
  - 200 + 0 结果 → **EMPTY**
  - 202（anomaly）/ 403 / 429 → **BLOCKED**
  - 传输错误 / 5xx / 超时 → **NET_ERROR**
  - 被停止信号中断 → **SKIPPED**

## 协调者裁定（覆盖 SPEC 未定细节）

1. **FATAL 口径**：params 校验失败（query 缺失/非 str、page < 1）→ FATAL（对齐
   FetchFbGroupPosts 的缺参数 FATAL）。缺 API key 的 FATAL 与 SERP 无关（本原子无
   key），不适用。
2. **节奏的 wait 次数断言**：单测里 mock `ctx.wait` 计数——正常路径 1 次（请求后
   节奏）、202 路径 2 次（退避 + 节奏）。SKIPPED 判定在 HTTP 前还是后：先检查
   `ctx.stopped()` 再发请求 → 返回 SKIPPED 且 wait 0 次。
3. **`_http_get` 的传输错误**：`urllib.error.URLError` / `HTTPError` / `socket.timeout`
   原样上抛（由原子 run 捕获映射 NET_ERROR）；HTTP 5xx 状态码直接返回
   (status, "") 由 run 映射 NET_ERROR——参考 facebook_group.py 的 _http_json 模式
   （它上抛传输异常，由原子 catch）。具体实现以 facebook_group.py 原子为准：
   读 `fetcher/fetcher/atoms/facebook_group.py` 的 FetchFbGroupPosts.run 与
   `_http_json`，Outcome 映射与 catch 结构对齐它。
4. **gzip 解压**：`Content-Encoding: gzip` 时解压（urllib 不自动解压）。
5. **quote**：`urllib.parse.quote(query)`（默认 safe='/'，查询词含空格会编码为 %20，
   符合 DDG 端点）。
6. **标题净化**：strip + html.unescape（&amp; → & 等）；不处理 `| Facebook` 后缀
   （那是 FbDiscoverTask 的职责，见 Step 1.3 brief）。
7. **fixture**：从 `docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html`
   截取（或直接引用该文件路径读入测试，避免复制大文件；若复制进 fetcher/tests/
   则保持小样本 <20KB）。

## 代码库上下文

- `fetcher/fetcher/atoms/facebook_group.py`：`_http_json` 模块级函数 + `FetchFbGroupPosts`
  原子 run 的 Outcome 映射/异常 catch/节奏 wait 模式——本原子对齐它。
- `fetcher/fetcher/core/context.py`：WorkerContext（`ctx.wait(seconds) -> bool` 返回
  True=被停止/中止中断；`ctx.stopped()`）。
- `fetcher/fetcher/core/types.py`：`ActionResult`（outcome/data）与 `Outcome` 枚举
  （OK/EMPTY/BLOCKED/NET_ERROR/FATAL/SKIPPED 等）——读它确认枚举名与构造方式。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_facebook_discover.py"`；回归：`-p "test_facebook*.py"`（含
  test_facebook.py、test_facebook_group.py、test_fb_plugin.py 等）。

## TDD 纪律

1. 先写失败测试 → RED（记录输出）→ 最小实现 → GREEN。mock 只在 HTTP 层
   （monkeypatch `_http_get`），parse/classify 用真实 fixture/真实 URL。
2. 测试覆盖（brief 已列）：parse 样本结构/标题实体、classify 各形态
   （帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、202→BLOCKED、
   停止→SKIPPED、节奏 wait 次数（含 202 双 wait）、params 校验 FATAL、gzip 解压。
3. 测试输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/atoms/facebook_discover.py`、
  `fetcher/tests/test_facebook_discover.py`（+可选 fixture 文件）、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 1.2 ...`。
