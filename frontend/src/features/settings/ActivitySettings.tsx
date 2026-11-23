import { Navigate } from 'react-router'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { timeAgo } from '@/features/documents/format'
import { type ActivityItem, useActivity } from '@/features/insights/api'
import { SettingsSection } from '@/features/settings/SettingsLayout'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { atLeast } from '@/lib/types'

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Turns an activity row into a readable sentence. Unknown actions fall back to the raw name. */
function describe(a: ActivityItem): string {
  const who = a.actor ?? 'Someone'
  const m = a.meta as Record<string, string | number | undefined>
  switch (a.action) {
    case 'workspace.created':
      return `${who} created the workspace`
    case 'workspace.renamed':
      return `${who} renamed the workspace from “${m.from}” to “${m.to}”`
    case 'workspace.ai_consent_granted':
      return `${who} allowed AI processing`
    case 'workspace.ownership_transferred':
      return `${who} transferred ownership`
    case 'invitation.created':
      return `${who} created an invite link (${m.role}${m.email ? ` for ${m.email}` : ''})`
    case 'member.joined':
      return `${who} joined as ${m.role}`
    case 'member.left':
      return `${who} left the workspace`
    case 'member.removed':
      return `${who} removed a member`
    case 'member.role_changed':
      return `${who} changed a member's role from ${m.from} to ${m.to}`
    case 'document.uploaded':
      return `${who} uploaded “${m.filename}”`
    case 'document.indexed':
      return `A document was indexed (${plural(Number(m.pages), 'page')}, ${plural(Number(m.chunks), 'passage')})`
    case 'document.failed':
      return `A document couldn't be processed (${m.code})`
    case 'document.renamed':
      return `${who} renamed a document`
    case 'document.deleted':
      return `${who} deleted “${m.title}”`
    case 'collection.created':
      return `${who} created the collection “${m.name}”`
    case 'collection.deleted':
      return `${who} deleted the collection “${m.name}”`
    default:
      return `${who}: ${a.action}`
  }
}

export function ActivitySettings() {
  const workspace = useCurrentWorkspace()
  const isAdmin = atLeast(workspace.role, 'admin')
  const { data, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } = useActivity(workspace.id, isAdmin)
  if (!isAdmin) return <Navigate to={wsPath(workspace.id, 'settings')} replace />
  const items = data?.pages.flatMap((p) => p.items) ?? []

  return (
    <SettingsSection title="Activity" description="Recent changes in this workspace. Visible to admins only.">
      {isPending ? (
        <div className="grid gap-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-8" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">Nothing has happened yet.</p>
      ) : (
        <>
          <ol className="divide-y">
            {items.map((a) => (
              <li key={a.id} className="flex items-baseline justify-between gap-4 py-2.5 text-sm">
                <span className="min-w-0">{describe(a)}</span>
                <time dateTime={a.created_at} title={new Date(a.created_at).toLocaleString()} className="text-muted-foreground shrink-0 text-xs">
                  {timeAgo(a.created_at)}
                </time>
              </li>
            ))}
          </ol>
          {hasNextPage ? (
            <Button variant="outline" size="sm" className="mt-4" disabled={isFetchingNextPage} onClick={() => void fetchNextPage()}>
              {isFetchingNextPage ? 'Loading…' : 'Show older'}
            </Button>
          ) : null}
        </>
      )}
    </SettingsSection>
  )
}
