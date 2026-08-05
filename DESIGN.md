# 设计规范（采集平台管理系统）

> 适用范围：`platform/web` 前端。本文档是设计约定的唯一文字来源，新增页面/组件前先读本文件。

## 1. 技术栈

- React 18 + TypeScript + Vite
- Tailwind CSS 3 + `tailwindcss-animate`
- shadcn/ui 组件库（源码在 `src/components/ui/`，可改但保持风格统一）
- 图标：lucide-react；图表：recharts；路由：react-router-dom v6

## 2. 颜色系统（Token 唯一来源）

所有颜色定义在 `src/styles/tokens.css`，**禁止在组件中散落硬编码色值**。

- 新增颜色流程：先在 `tokens.css` 加 token → 再在 `tailwind.config.js` 映射（或用 `hsl(var(--xxx))`）。
- 值一律为「H S% L%」三段 HSL 通道（不含 `hsl()` 括号），与 `hsl(var(--xxx))` 配套。
- 双主题：`:root` 为 light，`.dark` 为 dark，两组 token **必须一一对应、成对新增**。

Token 分组：

| 分组 | 命名 | 用途 |
|---|---|---|
| shadcn 语义色 | `--background` / `--foreground` / `--card` / `--primary` / `--muted` / `--accent` / `--border` / `--input` / `--ring` 等 | 全局基础色，role 与 role-foreground 配对 |
| 业务状态色 | `--status-{success\|warning\|info\|danger\|neutral}` 及 `-foreground` | 状态徽标、提示 |
| 积压高亮 | `--backlog` / `--backlog-foreground` | 积压任务卡片、徽标 |
| 图表色 | `--chart-{collected\|consumed\|grid\|axis\|tooltip-bg\|tooltip-border}` | Dashboard recharts 专用 |
| 布局尺寸 | `--sidebar-width`、`--radius` | 双主题共用，仅 `:root` 定义 |

## 3. 圆角与阴影

- 圆角以 `--radius: 0.625rem` 为基准：`sm = -4px`、`md = -2px`、`lg = 基准`、`xl = +4px`。
- 阴影仅 `shadow-xs`（`0 1px 2px rgb(0 0 0 / 0.05)`）为基准微阴影，弹层用 `shadow-md`。

## 4. 字体与排版

- 页面标题：`text-xl font-semibold`；描述：`text-sm text-muted-foreground`（见 `PageHeader`）。
- 正文 / 表格 / 表单控件：`text-sm`。
- 次要信息：`text-muted-foreground`；更弱的辅助信息：`text-xs text-muted-foreground`。
- 导航选中态加 `font-medium`，未选中 `text-muted-foreground`。

## 5. 控件规范

### 按钮（Button）

- 工具栏 / 分页条内统一用 `variant="outline" size="sm"`：`h-8`、`text-sm font-medium`、图标 `h-4 w-4` 间距 `gap-1.5`。
- 主操作才用 `default` 变体，危险操作用 `destructive`。

### 下拉（Select）

- 与按钮并排时**必须对齐按钮的视觉指标**：`h-8` + `text-sm font-medium`（SelectTrigger 默认 `font-normal`，需显式加 `font-medium`）。
- 显示文字较长的 trigger（如「每页 20 条」）**不要写死小宽度**，让 `w-fit` 自适应，避免右侧箭头压住文字；纯占位筛选可用固定宽（如 `w-36`）。
- 列表项文案与 trigger 显示文案保持一致（如「每页 20 条」而非孤零零的「20」）。

### 输入框（Input）

- 搜索框 `w-64` 起，占位文案说明可搜字段；页内搜索统一走 `useDebouncedValue`（500ms 防抖，见 `pages/data/shared.tsx`）。

### 状态徽标（Badge）

- 成功态：`border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400`（outline 变体 + 透明度色阶）。
- 中性 / 待处理：`secondary` 或 `outline` + `text-muted-foreground`；失败：`destructive`。
- 同一状态在全局保持同一配色，参考 `ShopsTab.shopStatusBadge`。

## 6. 布局

- 整体：`Layout.tsx` 左侧固定导航（宽 `w-sidebar` = 14rem，`bg-card` + 右侧 `border-r`），右侧 `main` 滚动内容区。
- 页面骨架：`PageHeader`（标题 + 描述 + 右侧操作区 `extra`）→ 筛选工具栏（`flex flex-wrap items-center gap-4`）→ 内容 → 底部分页。
- 主题切换：浅色 → 深色 → 跟随系统 循环（`lib/theme.ts`），入口在侧栏底部。

## 7. 页面状态

统一使用 `components/PageState.tsx`：

- 加载：`LoadingState`（3 条 `Skeleton`）
- 错误：`ErrorState`（`border-destructive/40 bg-destructive/10` 容器 + 重试按钮）
- 空：`EmptyState`（虚线边框容器 + Inbox 图标）

Toast 全局只挂一次（Layout 中 `Toaster position="top-right"`），页内不再各自挂载。

## 8. 表格与分页

- 表格外层包 `rounded-lg border border-border`；数值列 `text-right`。
- 分页统一用 `PaginationBar`（`pages/data/shared.tsx`）：
  - 左侧：页码信息（`第 x / y 页 · 共 N 条`）+ 每页条数选择器（信息与密度控制同组）。
  - 右侧：上一页 / 下一页按钮 + 「跳至 __ 页 [跳转]」。
  - 时间戳直接展示库内北京时间字符串（`showTime`），不做时区换算。

## 9. 其他约定

- 类名合并一律用 `cn()`（`@/lib/utils`）。
- 注释用中文，文件顶部用一行注释说明模块职责。
- 提交前跑 `npx tsc -b` 保证类型通过。
