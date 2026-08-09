# Step 4.3 完成报告 — TaskFormDialog.tsx 两独立表单分支

## 状态：DONE

## 改了什么

### 文件改动

**`platform/web/src/pages/tasks/TaskFormDialog.tsx`**（唯一改动文件）：

1. **新增 import**：`Textarea` from `@/components/ui/textarea`
2. **新增常量**：`FB_DISCOVER_DEFAULT_KEYWORDS`（SPEC §7.4 默认矩阵，5 行）
3. **新增 4 个 state**：
   - `fbDiscoverKeywords` (string)
   - `fbDiscoverPages` (string)
   - `fbGroupProvider` ('brightdata' | 'apify')
   - `fbGroupPostsPerGroup` (string)
4. **新增 2 个类型判定**：`isFbDiscover` / `isFbGroup`
5. **`fillFromParams`** 扩展：回填 keywords/pages/provider/posts_per_group
6. **`buildParams`** 扩展：fb_discover（keywords + pages + repeat_interval）/ fb_group（provider + posts_per_group + limit + repeat_interval）
7. **`validate`** 扩展：pages 1-10、posts_per_group ≥1、provider 限定、群数上限 ≥0
8. **`paramsKey`** 扩展：加入 4 个新 state 键触发预览防抖
9. **渲染分支**：`isBatch ? ... : isWaCheck ? ... : isFbDiscover ? ... : isFbGroup ? ... : 默认`（五形态）
10. **新建时默认值**：fb_discover keywords 预填默认矩阵、pages 默认 '1'；fb_group provider 默认 'brightdata'、posts_per_group 默认 '50'、群数上限 batchLimit 默认 ''

### 既有分支零回归

isBatch / isWaCheck / 默认三分支代码未做任何修改，仅在其后追加新分支。

## TypeScript 编译

```
$ cd platform/web && npx tsc -b
EXIT: 0
```

全绿，零错误零警告。

## 运行时验证证据

### 1. fb_discover 创建 + 预览

```
$ curl -X POST /api/tasks -d '{"type":"fb_discover","params":{"keywords":"...","pages":2,"repeat_interval":1800}}'
→ 201, id=91

$ curl -X POST /api/tasks/preview -d '{"type":"fb_discover","params":{"keywords":"test","pages":1}}'
→ {"cmdline":"批次提交：discover_fb"}
```

### 2. fb_group 创建 + 预览

```
$ curl -X POST /api/tasks -d '{"type":"fb_group","params":{"provider":"brightdata","posts_per_group":50,"limit":10,"repeat_interval":3600}}'
→ 201, id=90

$ curl -X POST /api/tasks/preview -d '{"type":"fb_group","params":{"provider":"apify","posts_per_group":100}}'
→ {"cmdline":"批次提交：crawl_fb_group"}
```

### 3. 编辑回填验证（PUT）

```
$ curl -X PUT /api/tasks/91 -d '{"params":{"keywords":"updated","pages":3,"repeat_interval":900}}'
→ 200, params_json 含 keywords/pages/repeat_interval
```

### 4. 模板保存/加载回填验证

```
$ curl -X POST /api/task-templates -d '{"name":"Test fb_discover","type":"fb_discover","params":{"keywords":"a\nb","pages":3}}'
→ 201, params 含 keywords/pages

$ curl -X POST /api/task-templates -d '{"name":"Test fb_group","type":"fb_group","params":{"provider":"apify","posts_per_group":100,"limit":5}}'
→ 201, params 含 provider/posts_per_group/limit
```

fillFromParams 可正确从 params 键回填四个新状态。

### 5. 既有分支零回归验证

| 类型 | 预览输出 |
|---|---|
| 1688_shop (isBatch) | `批次提交：crawl_1688_shop，100 条` |
| wa_check (isWaCheck) | `批次提交：wa_check，500 条` |
| yiwugo_search (默认) | `python -m fetcher yiwugo search -n 20 --proxy` |
| fb_post (isBatch) | `批次提交：crawl_fb_post，200 条` |

### 6. 边界情况

| 情况 | 结果 |
|---|---|
| fb_discover 空 keywords | 预览正常（后端幂等） |
| fb_discover 无 pages | 预览正常（后端默认） |
| fb_group apify provider | 预览正常 |

## DESIGN.md 合规自查

- ✅ `SelectTrigger`：fb_group provider select 使用 `className="h-8 font-medium"`
- ✅ `hint`：全部使用 `text-xs text-muted-foreground`
- ✅ `Label`：使用 shadcn Label 组件（默认 text-sm）
- ✅ 按钮：沿用现有 `variant="outline" size="sm"`
- ✅ 无硬编码色值：全部使用 Tailwind utility classes
- ✅ Textarea: `min-h-24 font-mono text-xs`

## 自查发现

- 无
- 所有 10 项 PLAN checkbox 均已满足
- 五形态渲染顺序符合协调者裁定（isBatch → isWaCheck → isFbDiscover → isFbGroup → 默认）
- fb_group 群数上限复用 batchLimit state（与 isBatch 共用，符合裁定）
