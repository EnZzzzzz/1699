import { NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, ListTodo, Network, ServerCog, Database, Sun, Moon, Monitor } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTheme, type Theme } from '@/lib/theme'
import { Toaster } from '@/components/ui/sonner'

const navItems = [
  { to: '/', label: '整体看板', icon: LayoutDashboard, end: true },
  { to: '/tasks', label: '任务管理', icon: ListTodo, end: false },
  { to: '/dispatcher', label: '调度器', icon: Network, end: false },
  { to: '/data', label: '数据浏览', icon: Database, end: false },
  { to: '/providers', label: '供应商', icon: ServerCog, end: false },
]

const themeMeta: Record<Theme, { label: string; icon: typeof Sun }> = {
  light: { label: '浅色', icon: Sun },
  dark: { label: '深色', icon: Moon },
  system: { label: '跟随系统', icon: Monitor },
}

/** 主题循环切换：浅色 → 深色 → 跟随系统 */
function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const order: Theme[] = ['light', 'dark', 'system']
  const next = order[(order.indexOf(theme) + 1) % order.length]
  const { label, icon: Icon } = themeMeta[theme]

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      title={`主题：${label}（点击切换为${themeMeta[next].label}）`}
      aria-label={`切换主题，当前为${label}`}
      className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}

export default function Layout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* 左侧导航 */}
      <aside className="flex w-sidebar shrink-0 flex-col border-r border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <Database className="h-5 w-5 text-success" />
          <div>
            <div className="text-sm font-semibold leading-tight">采集平台</div>
            <div className="text-xs text-muted-foreground">管理系统 · P0</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent font-medium text-foreground'
                    : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <span className="text-xs text-muted-foreground">1688 / 义乌购采集系统</span>
          <ThemeToggle />
        </div>
      </aside>

      {/* 内容区 */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* 全局 toast 挂载点（页内不再各自挂 Toaster） */}
      <Toaster position="top-right" />
    </div>
  )
}
