import { AlertCircle, ChevronLeft, ChevronRight, Download, Loader2, RotateCcw, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  downloadDocument,
  useCollections,
  useDocument,
  useDocumentPage,
  useReprocessDocument,
} from '@/features/documents/api'
import { FileTypeIcon, StatusBadge } from '@/features/documents/components/bits'
import { fileTypeLabel, formatBytes, timeAgo } from '@/features/documents/format'
import { DocumentActions } from '@/features/documents/components/DocumentActions'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { toApiError } from '@/lib/api'
import { atLeast } from '@/lib/types'

/** Side panel with the document's details and a text preview, page by page. */
export function DocumentDrawer({ documentId, onClose }: { documentId: string | null; onClose: () => void }) {
  const workspace = useCurrentWorkspace()
  const { data: doc } = useDocument(workspace.id, documentId)
  return (
    <Sheet open={!!documentId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
        {!doc ? (
          <div className="grid gap-3 p-6">
            <SheetTitle className="sr-only">Loading document</SheetTitle>
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        ) : (
          <>
            <SheetHeader className="border-b p-5 pr-12">
              <div className="flex items-start gap-3">
                <FileTypeIcon type={doc.file_type} />
                <div className="min-w-0 flex-1">
                  <SheetTitle className="truncate text-left text-lg">{doc.title}</SheetTitle>
                  <SheetDescription className="text-left">
                    {fileTypeLabel(doc.file_type)} · {formatBytes(doc.size_bytes)} · added {timeAgo(doc.created_at)}
                    {doc.uploaded_by ? ` by ${doc.uploaded_by.display_name}` : ''}
                  </SheetDescription>
                </div>
                <DocumentActions doc={doc} onDeleted={onClose} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <StatusBadge doc={doc} />
                <CollectionChips ids={doc.collection_ids} />
                <div className="ml-auto flex gap-2">
                  {doc.status === 'ready' ? (
                    <Button size="sm" asChild>
                      <Link to={`${wsPath(workspace.id, 'ask')}?doc=${doc.id}`}>
                        <Sparkles aria-hidden /> Ask about this
                      </Link>
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void downloadDocument(workspace.id, doc.id).catch((e) => toast.error(toApiError(e).message))}
                  >
                    <Download aria-hidden /> Download
                  </Button>
                </div>
              </div>
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {doc.status === 'ready' && doc.page_count ? (
                <Preview documentId={doc.id} pageCount={doc.page_count} unit={doc.page_unit} />
              ) : doc.status === 'failed' ? (
                <Failed id={doc.id} message={doc.error_message} />
              ) : (
                <p className="text-muted-foreground flex items-center gap-2 p-6 text-sm" role="status">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Extracting text and splitting it into searchable passages…
                </p>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function CollectionChips({ ids }: { ids: string[] }) {
  const workspace = useCurrentWorkspace()
  const { data: collections = [] } = useCollections(workspace.id)
  const names = collections.filter((c) => ids.includes(c.id)).map((c) => c.name)
  return (
    <>
      {names.map((n) => (
        <span key={n} className="bg-accent text-accent-foreground rounded-full px-2 py-0.5 text-xs font-medium">
          {n}
        </span>
      ))}
    </>
  )
}

function Preview({ documentId, pageCount, unit }: { documentId: string; pageCount: number; unit: 'page' | 'section' }) {
  const workspace = useCurrentWorkspace()
  const [page, setPage] = useState(1)
  const { data, isPending, isError } = useDocumentPage(workspace.id, documentId, page, true)
  const unitLabel = unit === 'page' ? 'Page' : 'Section'
  return (
    <div>
      <nav
        aria-label="Preview pages"
        className="bg-card/95 sticky top-0 flex items-center justify-between border-b px-5 py-2 backdrop-blur"
      >
        <Button variant="ghost" size="icon-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label={`Previous ${unitLabel.toLowerCase()}`}>
          <ChevronLeft aria-hidden />
        </Button>
        <span className="text-muted-foreground text-sm" aria-live="polite">
          {unitLabel} {page} of {pageCount}
        </span>
        <Button variant="ghost" size="icon-sm" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)} aria-label={`Next ${unitLabel.toLowerCase()}`}>
          <ChevronRight aria-hidden />
        </Button>
      </nav>
      <article className="px-6 py-5">
        {isPending ? (
          <div className="grid gap-2">
            {[90, 100, 95, 70].map((w) => (
              <Skeleton key={w} className="h-4" style={{ width: `${w}%` }} />
            ))}
          </div>
        ) : isError ? (
          <p className="text-destructive text-sm">This {unitLabel.toLowerCase()} couldn&apos;t be loaded.</p>
        ) : (
          data.text.split('\n\n').map((para, i) => (
            // Paragraphs have no ids; their order never changes, so the index is a stable key.
            <p key={i} className="mb-4 text-[0.95rem] leading-relaxed">
              {para}
            </p>
          ))
        )}
        {unit === 'section' ? (
          <p className="text-muted-foreground mt-6 border-t pt-4 text-xs">
            Word and text files don&apos;t have fixed pages, so DocuMind splits them into sections.
          </p>
        ) : null}
      </article>
    </div>
  )
}

function Failed({ id, message }: { id: string; message: string | null }) {
  const workspace = useCurrentWorkspace()
  const reprocess = useReprocessDocument(workspace.id)
  return (
    <div className="p-6">
      <div className="border-destructive/30 bg-destructive/5 flex gap-3 rounded-lg border p-4">
        <AlertCircle className="text-destructive mt-0.5 size-5 shrink-0" aria-hidden />
        <div>
          <p className="text-sm font-medium">This file couldn&apos;t be processed</p>
          <p className="text-muted-foreground mt-1 text-sm">{message ?? 'Something went wrong.'}</p>
          {atLeast(workspace.role, 'member') ? (
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              disabled={reprocess.isPending}
              onClick={() => reprocess.mutate(id, { onError: (e) => toast.error(toApiError(e).message) })}
            >
              <RotateCcw aria-hidden /> Try again
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
