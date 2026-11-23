import { AlertCircle, CheckCircle2, Copy, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/features/documents/format'
import { useShallow } from 'zustand/react/shallow'
import { type UploadItem, useUploads } from '@/features/documents/uploads'
import { cn } from '@/lib/utils'

/** Bottom-right panel listing uploads in progress, with per-file progress and results. */
export function UploadTray({ workspaceId }: { workspaceId: string }) {
  // useShallow: the filtered array is new on every call; compare items, not identity.
  const items = useUploads(useShallow((s) => s.items.filter((i) => i.workspaceId === workspaceId)))
  const clearFinished = useUploads((s) => s.clearFinished)
  if (items.length === 0) return null
  const busy = items.filter((i) => i.state === 'waiting' || i.state === 'uploading').length

  return (
    <aside
      aria-label="Uploads"
      className="bg-popover fixed right-4 bottom-20 z-40 w-[min(22rem,calc(100vw-2rem))] rounded-xl border shadow-[var(--shadow-lift)] md:bottom-6"
    >
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <p className="text-sm font-medium" role="status">
          {busy > 0 ? `Uploading ${busy} of ${items.length}` : `${items.length} upload${items.length === 1 ? '' : 's'} finished`}
        </p>
        {busy === 0 ? (
          <Button variant="ghost" size="icon-sm" onClick={clearFinished} aria-label="Close uploads">
            <X aria-hidden />
          </Button>
        ) : null}
      </header>
      <ul className="max-h-72 divide-y overflow-y-auto">
        {items.map((item) => (
          <UploadRow key={item.id} item={item} />
        ))}
      </ul>
    </aside>
  )
}

function UploadRow({ item }: { item: UploadItem }) {
  const failed = item.state === 'rejected' || item.state === 'error'
  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-sm">{item.name}</p>
        {item.state === 'done' ? <CheckCircle2 className="text-success size-4 shrink-0" aria-label="Uploaded" /> : null}
        {item.state === 'duplicate' ? <Copy className="text-muted-foreground size-4 shrink-0" aria-label="Duplicate" /> : null}
        {failed ? <AlertCircle className="text-destructive size-4 shrink-0" aria-label="Failed" /> : null}
      </div>
      {item.state === 'uploading' || item.state === 'waiting' ? (
        <div className="mt-1.5 flex items-center gap-2">
          <div
            className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full"
            role="progressbar"
            aria-label={`Uploading ${item.name}`}
            aria-valuenow={Math.round(item.progress * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="bg-primary h-full rounded-full transition-[width]" style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
          </div>
          <span className="text-muted-foreground w-14 text-right text-xs">{formatBytes(item.size)}</span>
        </div>
      ) : (
        <p className={cn('mt-0.5 text-xs', failed ? 'text-destructive' : 'text-muted-foreground')}>
          {item.message ?? (item.state === 'done' ? 'Uploaded' : '')}
        </p>
      )}
    </li>
  )
}
