import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { RouterProvider } from 'react-router/dom'
import { createRouter } from '@/app/router'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { onSessionEnded } from '@/lib/api'
import { createQueryClient, queryKeys } from '@/lib/query-client'
import { syncThemeWithDocument } from '@/stores/preferences'

export function App() {
  const [queryClient] = useState(createQueryClient)
  const [router] = useState(createRouter)

  useEffect(() => syncThemeWithDocument(), [])

  // Session could not be refreshed (expired, revoked, or signed out in another tab).
  useEffect(
    () =>
      onSessionEnded(() => {
        // Only a *signed-in* user's session can "end". A first-time visitor also gets a 401
        // from /users/me (and a failed refresh) - the route guard sends them to login quietly.
        if (!queryClient.getQueryData(queryKeys.me)) return
        queryClient.clear()
        queryClient.setQueryData(queryKeys.me, null)
        const { pathname, search } = window.location
        const next = encodeURIComponent(pathname + search)
        void router.navigate(`/login?reason=session_ended&next=${next}`, { replace: true })
      }),
    [queryClient, router],
  )

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
