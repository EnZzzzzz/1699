# Task 3.3 终审修复轮报告（docs 级 2 处）

> 终审（final-review.md）结论「通过，附修复项」，本报告记录 2 处合并前必修的一行级文档修复。
> 终审清单第 1 条提到的两处行号（约 :36 与 :847-848）经全文检索确认：`daemon_task.py` 仅 195 行，
> `domain_suffix="1688.com"` / `queue="contact"` 错误写法只存在于模块 docstring 示例一处
> （`cli/main.py:218` 实际装配代码本就是 `.1688.com` / `args.queue`，无第二处需改）。

## 修复 1：`fetcher/fetcher/control/daemon_task.py` 模块 docstring 示例（:35-36）

**前：**

```
        task = DaemonTaskProxy(inner=ContactTask(), queue="contact",
                               site="1688", domain_suffix="1688.com")
```

**后：**

```
        task = DaemonTaskProxy(inner=ContactTask(), queue="crawl_1688_contact",
                               site="1688", domain_suffix=".1688.com")
```

理由：`domain_suffix` 为 substr 后缀匹配，少前导点会误匹配 `evil1688.com` 类域名；
`"contact"` 非真实队列名，P0 唯一队列是 `crawl_1688_contact`。

## 修复 2：`fetcher/README.md` daemon 说明段（:44-45）

**前：**

```
`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
跑完 N 个后退出，作冒烟/联调的收工手段。
```

**后：**

```
`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
每个 worker 跑完 N 个后退出，作冒烟/联调的收工手段。
```

理由：`--limit` 是 per-worker 口径（`cli/main.py:56-57` help 原文「每个 worker 本次最多采集量」），
README 旧表述易被误读为全局总量。

## 测试验证

```
$ cd fetcher && python -m pytest tests -x -q
231 passed, 2 subtests passed in 8.94s
```
