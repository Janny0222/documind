import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router'
import { PageHeader } from '@/components/EmptyState'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { atLeast } from '@/lib/types'
import { wsPath } from '@/layouts/nav'
import { cn } from '@/lib/utils'

/** Settings is one of the few places where a side menu earns its space. */
export function SettingsLayout() {
  const workspace = useCurrentWorkspace()
  const links = [
    { to: 'settings', label: 'Workspace', end: true },
    { to: 'settings/members', label: 'Members' },
    { to: 'settings/account', label: 'Your account' },
    ...(atLeast(workspace.role, 'admin') ? [{ to: 'settings/activity', label: 'Activity' }] : []),
  ]
  return (
    <>
      <PageHeader title="Settings" description={workspace.name} />
      <div className="grid gap-6 md:grid-cols-[200px_minmax(0,1fr)] md:gap-10">
        <nav aria-label="Settings" className="-mx-1 flex gap-1 overflow-x-auto md:mx-0 md:flex-col">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={wsPath(workspace.id, l.to)}
              end={l.end}
              className={({ isActive }) =>
                cn(
                  'shrink-0 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
                  isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </>
  )
}

export function SettingsSection({
  title,
  description,
  children,
  tone = 'default',
}: {
  title: string
  description?: ReactNode
  children: ReactNode
  tone?: 'default' | 'danger'
}) {
  return (
    <section
      className={cn('bg-card rounded-xl border p-5 md:p-6', tone === 'danger' && 'border-destructive/30')}
      aria-label={title}
    >
      <h2 className={cn('text-base font-semibold', tone === 'danger' && 'text-destructive')}>{title}</h2>
      {description ? <p className="text-muted-foreground mt-1 mb-5 text-sm">{description}</p> : <div className="mb-5" />}
      {children}
    </section>
  )
}
