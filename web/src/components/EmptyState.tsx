import { Button } from '@/components/ui/button'
import { Inbox, Rocket, AlertCircle } from 'lucide-react'

interface EmptyStateProps {
  icon?: 'inbox' | 'rocket' | 'error'
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
}

const ICONS = {
  inbox: Inbox,
  rocket: Rocket,
  error: AlertCircle,
}

export function EmptyState({ icon = 'inbox', title, description, actionLabel, onAction }: EmptyStateProps) {
  const Icon = ICONS[icon]
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-16 text-center">
      <Icon className="h-10 w-10 text-muted-foreground/50" />
      <div>
        <p className="font-medium">{title}</p>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actionLabel && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}

/** 后端端点未实现（501/404）时的统一空态 */
export function NotImplementedState({ feature }: { feature: string }) {
  return (
    <EmptyState
      icon="rocket"
      title="功能即将上线"
      description={`${feature}的后端接口尚未就绪，当前展示为占位空态。`}
    />
  )
}
