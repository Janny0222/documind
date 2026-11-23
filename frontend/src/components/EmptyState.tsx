import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  children?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, children, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center px-6 py-12 text-center', className)}>
      <span className="bg-accent text-accent-foreground grid size-11 place-items-center rounded-xl">
        <Icon className="size-5" aria-hidden />
      </span>
      <h3 className="mt-4 text-base font-semibold">{title}</h3>
      {children ? <div className="text-muted-foreground mt-1.5 max-w-sm text-sm">{children}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 md:mb-8">
      <div>
        <h1 className="text-2xl font-bold md:text-[1.75rem]">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1">{description}</p> : null}
      </div>
      {actions}
    </div>
  )
}

/** A bento tile. Surfaces are white with a hairline border; elevation is reserved for the hero. */
export function Tile({ className, children, ...rest }: React.ComponentProps<'section'>) {
  return (
    <section className={cn('bg-card rounded-xl border p-5 md:p-6', className)} {...rest}>
      {children}
    </section>
  )
}
