import { NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, ListTodo, Network, Settings2, Database, Server, Workflow } from 'lucide-react'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/tasks', label: '任务', icon: ListTodo },
  { to: '/flows', label: '流水线', icon: Workflow },
  { to: '/pool', label: 'IP 池', icon: Network },
  { to: '/workers', label: 'Worker', icon: Server },
  { to: '/providers', label: '厂商配置', icon: Settings2 },
  { to: '/data', label: '数据', icon: Database },
]

export default function Layout() {
  return (
    <div className="flex h-screen bg-muted/40">
      <aside className="flex w-56 flex-col border-r bg-background">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <Network className="h-5 w-5 text-primary" />
          <span className="text-base font-semibold">1688 采集平台</span>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3 text-xs text-muted-foreground">本机单机部署 · v1</div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6">
          <Outlet />
        </div>
      </main>
      <Toaster richColors position="top-right" />
    </div>
  )
}
