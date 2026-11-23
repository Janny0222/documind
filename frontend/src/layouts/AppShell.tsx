import { Search } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'
import { Logo, LogoMark } from '@/components/brand/Logo'
import { DemoBanner } from '@/features/workspaces/components/DemoEntry'
import { WorkspaceSwitcher } from '@/features/workspaces/components/WorkspaceSwitcher'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { CommandPalette } from '@/layouts/CommandPalette'
import { NotificationBell } from '@/features/insights/NotificationBell'
import { mobileNav, primaryNav, wsPath } from '@/layouts/nav'
import { UserMenu } from '@/layouts/UserMenu'
import { cn } from '@/lib/utils'
import { isMac, useUi } from '@/stores/ui'

/**
 * Top navigation instead of a permanent sidebar: the page content gets the full width, and
 * the command palette (⌘K) is the fast path everywhere. On phones the nav moves to a bottom
 * tab bar within thumb reach.
 */
export function AppShell() {
  const workspace = useCurrentWorkspace()
  const openCommand = useUi((s) => s.setCommandOpen)

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="bg-primary text-primary-foreground sr-only z-50 rounded-md px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <header className="bg-background/85 sticky top-0 z-30 border-b backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
        <div className="mx-auto flex h-14 max-w-[1240px] items-center gap-2 px-4 sm:px-6">
          <NavLink to={wsPath(workspace.id, '')} aria-label="DocuMind home" className="mr-1 rounded-md">
            <Logo className="hidden sm:inline-flex" />
            <LogoMark className="sm:hidden" />
          </NavLink>
          <span className="bg-border hidden h-5 w-px sm:block" aria-hidden />
          <WorkspaceSwitcher />

          <nav aria-label="Primary" className="ml-2 hidden shrink-0 items-center gap-0.5 md:flex lg:ml-4">
            {primaryNav.map((item) => (
              <NavLink
                key={item.label}
                to={wsPath(workspace.id, item.to)}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-2.5 py-1.5 text-sm font-medium whitespace-nowrap transition-colors lg:px-3',
                    isActive
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => openCommand(true)}
              className="text-muted-foreground hover:text-foreground hover:bg-muted flex h-9 items-center gap-2 rounded-md border px-2.5 text-sm transition-colors xl:w-64"
              aria-label="Open command palette"
            >
              <Search className="size-4" aria-hidden />
              <span className="hidden xl:inline">Search or ask…</span>
              <kbd className="bg-muted ml-auto hidden rounded px-1.5 py-0.5 font-sans text-[0.7rem] xl:inline">
                {isMac() ? '⌘' : 'Ctrl'} K
              </kbd>
            </button>
            <NotificationBell />
            <UserMenu />
          </div>
        </div>
      </header>
      <DemoBanner />

      <main id="main" className="mx-auto max-w-[1240px] px-4 pt-6 pb-28 sm:px-6 md:pt-8 md:pb-16">
        <Outlet />
      </main>

      <MobileTabBar />
      <CommandPalette />
    </div>
  )
}

function MobileTabBar() {
  const workspace = useCurrentWorkspace()
  const items = mobileNav
  return (
    <nav
      aria-label="Primary"
      className="bg-background/95 fixed inset-x-0 bottom-0 z-30 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => (
          <li key={item.label}>
            <NavLink
              to={wsPath(workspace.id, item.to)}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'flex min-h-14 flex-col items-center justify-center gap-1 text-[0.7rem] font-medium',
                  isActive ? 'text-primary' : 'text-muted-foreground',
                )
              }
            >
              <item.icon className="size-5" aria-hidden />
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
