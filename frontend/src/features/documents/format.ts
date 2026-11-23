import type { DocumentItem, FileType } from '@/lib/types'

const typeLabels: Record<FileType, string> = { pdf: 'PDF', docx: 'DOCX', txt: 'TXT' }
export const fileTypeLabel = (type: FileType) => typeLabels[type]

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function pagesLabel(doc: Pick<DocumentItem, 'page_count' | 'page_unit'>) {
  if (!doc.page_count) return null
  const unit = doc.page_unit === 'page' ? 'page' : 'section'
  return `${doc.page_count} ${unit}${doc.page_count === 1 ? '' : 's'}`
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
export function timeAgo(iso: string) {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(seconds)
  if (abs < 60) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(seconds / 86400), 'day')
  return new Date(iso).toLocaleDateString()
}
