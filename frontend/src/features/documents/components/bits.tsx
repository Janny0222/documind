import { AlertCircle, CheckCircle2, FileText, Loader2 } from 'lucide-react'
import type { DocumentItem, FileType } from '@/lib/types'
import { cn } from '@/lib/utils'

const typeStyle: Record<FileType, { label: string; className: string }> = {
  pdf: { label: 'PDF', className: 'text-file-pdf bg-file-pdf/10' },
  docx: { label: 'DOCX', className: 'text-file-docx bg-file-docx/10' },
  txt: { label: 'TXT', className: 'text-file-txt bg-file-txt/10' },
}

export function FileTypeIcon({ type, className }: { type: FileType; className?: string }) {
  const t = typeStyle[type]
  return (
    <span className={cn('relative grid size-10 shrink-0 place-items-center rounded-lg', t.className, className)}>
      <FileText className="size-5" aria-hidden />
      <span className="sr-only">{t.label} file</span>
    </span>
  )
}

export function StatusBadge({ doc }: { doc: Pick<DocumentItem, 'status' | 'error_message'> }) {
  switch (doc.status) {
    case 'ready':
      return (
        <span className="text-success inline-flex items-center gap-1 text-xs font-medium">
          <CheckCircle2 className="size-3.5" aria-hidden /> Ready
        </span>
      )
    case 'failed':
      return (
        <span className="text-destructive inline-flex items-center gap-1 text-xs font-medium" title={doc.error_message ?? undefined}>
          <AlertCircle className="size-3.5" aria-hidden /> Failed
        </span>
      )
    case 'deleting':
      return <span className="text-muted-foreground text-xs">Deleting…</span>
    default:
      return (
        <span className="text-warning inline-flex items-center gap-1 text-xs font-medium" role="status">
          <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
          {doc.status === 'processing' ? 'Processing' : 'Queued'}
        </span>
      )
  }
}
