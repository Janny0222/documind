import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { LogoMark } from '@/components/brand/Logo'
import { useMe } from '@/features/auth/api'
import { safeNext } from '@/lib/format'

export function FullPageLoader({ label = 'Loading DocuMind' }: { label?: string }) {
  return (
    <div className="grid min-h-dvh place-items-center" role="status" aria-label={label}>
      <LogoMark className="size-9 animate-pulse" />
    </div>
  )
}

/** Wraps routes that need a signed-in user. The server still authorizes every request -
 *  this only decides what to render. */
export function RequireAuth({ children }: { children?: ReactNode }) {
  const { data: user, isPending, isError, refetch, isRefetching } = useMe()
  const location = useLocation()

  if (isPending) return <FullPageLoader />
  if (isError) {
    return (
      <div className="grid min-h-dvh place-items-center px-4">
        <div className="max-w-sm text-center">
          <LogoMark className="mx-auto size-9" />
          <h1 className="mt-5 text-xl font-bold">Can&apos;t reach DocuMind</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            The server may be waking up - free hosting sleeps when idle. This can take up to a
            minute.
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isRefetching}
            className="text-primary mt-5 text-sm font-medium hover:underline disabled:opacity-60"
          >
            {isRefetching ? 'Trying again…' : 'Try again'}
          </button>
        </div>
      </div>
    )
  }
  if (!user) {
    const next = location.pathname + location.search
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  return children ?? <Outlet />
}

/** Login/register pages: a signed-in user is sent on to the app. */
export function GuestOnly() {
  const { data: user, isPending } = useMe()
  const location = useLocation()
  if (isPending) return <FullPageLoader />
  if (user) {
    const next = new URLSearchParams(location.search).get('next')
    return <Navigate to={safeNext(next)} replace />
  }
  return <Outlet />
}
