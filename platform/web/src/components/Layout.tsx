import { NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, ListTodo, Network, MessageCircle, Database } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: '整体看板', icon: LayoutDashboard, end: true },
  { to: '/tasks', label: '任务管理', icon: ListTodo, end: false },
  { to: '/providers', label: '供应商', icon: Network, end: false },
  { to: '/wa', label: 'WhatsApp 账号', icon: MessageCircle, end: false },
]

export default function Layout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* 左侧导航 */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <Database className="h-5 w-5 text-emerald-400" />
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
        <div className="border-t border-border px-5 py-3 text-xs text-muted-foreground">
          1688 / 义乌购采集系统
        </div>
      </aside>

      {/* 内容区 */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
