import { isRouteErrorResponse, Link, useRouteError } from 'react-router'
import { LogoMark } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'

/** Error boundary for every route: a crash in one page never blanks the whole app. */
export function RouteError() {
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  if (import.meta.env.DEV && !notFound) console.error(error)

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <div className="max-w-sm text-center">
        <LogoMark className="mx-auto size-9" />
        <h1 className="mt-5 text-xl font-bold">{notFound ? 'Page not found' : 'Something broke on this page'}</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          {notFound
            ? "The address may be mistyped, or the page moved."
            : 'Reload to try again. If it keeps happening, the problem is on our side.'}
        </p>
        <div className="mt-6 flex justify-center gap-2">
          {!notFound ? (
            <Button variant="outline" onClick={() => window.location.reload()}>
              Reload
            </Button>
          ) : null}
          <Button asChild>
            <Link to="/">Go home</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
