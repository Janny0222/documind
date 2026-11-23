import { ExternalLink, FileWarning, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocumentPage } from '@/features/documents/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import type { Citation } from '@/lib/types'

/** Shows the page a citation points to, with the exact cited passage highlighted. */
export function SourcePanel({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const workspace = useCurrentWorkspace()
  const available = !!citation.document_id && !!citation.page_number
  const { data: page, isPending, isError } = useDocumentPage(
    workspace.id,
    citation.document_id ?? '',
    citation.page_number ?? 1,
    available,
  )
  const mark = useRef<HTMLElement>(null)
  useEffect(() => {
    mark.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [page, citation])

  const unit = citation.page_unit === 'page' ? 'Page' : 'Section'
  const start = citation.char_start ?? -1
  const end = citation.char_end ?? -1
  const canHighlight = !!page && start >= 0 && end > start && end <= page.text.length

  return (
    <aside aria-label="Source" className="bg-card flex h-full min-h-0 flex-col rounded-xl border">
      <header className="flex items-start gap-2 border-b p-4">
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-xs">Source</p>
          <h2 className="truncate font-semibold">{citation.document_title}</h2>
          {citation.page_number ? (
            <p className="text-muted-foreground text-sm">
              {unit} {citation.page_number}
            </p>
          ) : null}
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close source">
          <X aria-hidden />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5 text-[0.92rem] leading-relaxed">
        {!citation.document_id ? (
          <div>
            <p className="text-muted-foreground mb-3 flex items-center gap-2 text-sm">
              <FileWarning className="size-4" aria-hidden /> This document was deleted. The quoted passage was kept:
            </p>
            <blockquote className="border-primary/40 border-l-2 pl-3">{citation.excerpt}</blockquote>
          </div>
        ) : isPending && available ? (
          <div className="grid gap-2">
            {[95, 100, 88, 70].map((w) => (
              <Skeleton key={w} className="h-4" style={{ width: `${w}%` }} />
            ))}
          </div>
        ) : isError || !page ? (
          <blockquote className="border-primary/40 border-l-2 pl-3">{citation.excerpt}</blockquote>
        ) : canHighlight ? (
          <p className="whitespace-pre-wrap">
            {page.text.slice(0, start)}
            <mark ref={mark} className="bg-primary/15 text-foreground rounded px-0.5 ring-1 ring-primary/30">
              {page.text.slice(start, end)}
            </mark>
            {page.text.slice(end)}
          </p>
        ) : (
          <p className="whitespace-pre-wrap">{page.text}</p>
        )}
      </div>

      {citation.document_id ? (
        <footer className="border-t p-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to={`${wsPath(workspace.id, 'documents')}?doc=${citation.document_id}`}>
              <ExternalLink aria-hidden /> Open document
            </Link>
          </Button>
        </footer>
      ) : null}
    </aside>
  )
}
