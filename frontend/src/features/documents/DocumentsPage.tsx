import { useQueryClient } from '@tanstack/react-query'
import { FileUp, LayoutGrid, List, Search, Upload } from 'lucide-react'
import { type DragEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { EmptyState, PageHeader, Tile } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { type DocumentFilters, useCollections, useDocuments } from '@/features/documents/api'
import { DocumentActions } from '@/features/documents/components/DocumentActions'
import { DocumentDrawer } from '@/features/documents/components/DocumentDrawer'
import { FileTypeIcon, StatusBadge } from '@/features/documents/components/bits'
import { formatBytes, pagesLabel, timeAgo } from '@/features/documents/format'
import { UploadTray } from '@/features/documents/components/UploadTray'
import { ACCEPT_ATTR, enqueueUploads, MAX_FILE_MB } from '@/features/documents/uploads'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { atLeast, type DocumentItem, type DocumentSort, type FileType } from '@/lib/types'
import { cn } from '@/lib/utils'
import { usePreferences } from '@/stores/preferences'

const TYPES: { value: FileType | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'Word' },
  { value: 'txt', label: 'Text' },
]

const selectClass =
  'border-input bg-card h-9 rounded-md border px-2.5 text-sm focus-visible:outline-2 focus-visible:outline-ring'

export function DocumentsPage() {
  const workspace = useCurrentWorkspace()
  const qc = useQueryClient()
  const canUpload = atLeast(workspace.role, 'member')
  const [params, setParams] = useSearchParams()
  const view = usePreferences((s) => s.documentView)
  const setView = usePreferences((s) => s.setDocumentView)
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  // Filters live in the URL so a filtered view can be bookmarked or shared.
  const filters: DocumentFilters = {
    q: params.get('q') ?? undefined,
    type: (params.get('type') as FileType | null) ?? undefined,
    collection_id: params.get('collection') ?? undefined,
    sort: (params.get('sort') as DocumentSort | null) ?? 'newest',
  }
  const setParam = useCallback(
    (key: string, value: string | null) =>
      setParams(
        (p) => {
          if (value) p.set(key, value)
          else p.delete(key)
          return p
        },
        { replace: true },
      ),
    [setParams],
  )

  // Debounced search box -> URL.
  const [search, setSearch] = useState(filters.q ?? '')
  const currentQ = params.get('q') ?? ''
  useEffect(() => {
    const next = search.trim()
    if (next === currentQ) return // no-op: avoids a navigation loop
    const t = setTimeout(() => setParam('q', next || null), 250)
    return () => clearTimeout(t)
  }, [search, currentQ, setParam])

  const { data, isPending } = useDocuments(workspace.id, filters)
  const { data: collections = [] } = useCollections(workspace.id)
  const openDoc = params.get('doc')

  const upload = (files: FileList | File[] | null) => {
    if (files && files.length > 0) enqueueUploads(workspace.id, Array.from(files), qc)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (canUpload) upload(e.dataTransfer.files)
  }

  const hasFilters = !!(filters.q || filters.type || filters.collection_id)

  return (
    <div
      onDragEnter={(e) => canUpload && e.dataTransfer.types.includes('Files') && setDragging(true)}
      onDragOver={(e) => canUpload && e.preventDefault()}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={onDrop}
      className="relative"
    >
      <PageHeader
        title="Documents"
        description={data ? `${data.counts.all} in ${workspace.name}` : `Files in ${workspace.name}`}
        actions={
          canUpload ? (
            <>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept={ACCEPT_ATTR}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  upload(e.target.files)
                  e.target.value = '' // allow choosing the same file again
                }}
              />
              <Button onClick={() => fileInput.current?.click()}>
                <Upload aria-hidden /> Upload
              </Button>
            </>
          ) : null
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <label className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <span className="sr-only">Search documents by name</span>
          <Search className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name"
            className="border-input bg-card focus-visible:outline-ring h-9 w-full rounded-md border pr-3 pl-8 text-sm focus-visible:outline-2"
          />
        </label>
        <div role="group" aria-label="File type" className="flex gap-1">
          {TYPES.map((t) => {
            const active = (filters.type ?? '') === t.value
            const count = data ? (t.value ? data.counts[t.value] : data.counts.all) : null
            return (
              <button
                key={t.label}
                type="button"
                aria-pressed={active}
                onClick={() => setParam('type', t.value || null)}
                className={cn(
                  'h-9 rounded-md border px-3 text-sm font-medium transition-colors',
                  active ? 'border-primary bg-accent text-accent-foreground' : 'bg-card hover:bg-muted text-muted-foreground',
                )}
              >
                {t.label}
                {count !== null ? <span className="ml-1.5 text-xs opacity-70">{count}</span> : null}
              </button>
            )
          })}
        </div>
        <label className="sr-only" htmlFor="collection-filter">
          Collection
        </label>
        <select
          id="collection-filter"
          value={filters.collection_id ?? ''}
          onChange={(e) => setParam('collection', e.target.value || null)}
          className={selectClass}
        >
          <option value="">All collections</option>
          {collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="sort">
          Sort
        </label>
        <select id="sort" value={filters.sort} onChange={(e) => setParam('sort', e.target.value)} className={selectClass}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name A-Z</option>
          <option value="size">Largest first</option>
        </select>
        <div role="group" aria-label="Layout" className="ml-auto flex rounded-md border">
          {(['grid', 'list'] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              aria-label={v === 'grid' ? 'Grid view' : 'List view'}
              onClick={() => setView(v)}
              className={cn('grid size-9 place-items-center first:rounded-l-md last:rounded-r-md', view === v ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted')}
            >
              {v === 'grid' ? <LayoutGrid className="size-4" aria-hidden /> : <List className="size-4" aria-hidden />}
            </button>
          ))}
        </div>
      </div>

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <Tile>
          {hasFilters ? (
            <EmptyState
              icon={Search}
              title="No documents match"
              action={
                <Button variant="outline" onClick={() => (setSearch(''), setParams({}, { replace: true }))}>
                  Clear filters
                </Button>
              }
            >
              Try a different name or remove a filter.
            </EmptyState>
          ) : (
            <EmptyState
              icon={FileUp}
              title="Upload your first document"
              action={
                canUpload ? (
                  <Button onClick={() => fileInput.current?.click()}>
                    <Upload aria-hidden /> Choose files
                  </Button>
                ) : null
              }
            >
              {canUpload
                ? `Drop PDF, Word or text files here (up to ${MAX_FILE_MB} MB each). DocuMind extracts the text so you can search and ask about it.`
                : 'Nothing here yet. Members of this workspace can upload documents.'}
            </EmptyState>
          )}
        </Tile>
      ) : view === 'grid' ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {data.items.map((doc) => (
            <li key={doc.id}>
              <DocumentCard doc={doc} onOpen={() => setParam('doc', doc.id)} />
            </li>
          ))}
        </ul>
      ) : (
        <DocumentTable docs={data.items} onOpen={(id) => setParam('doc', id)} />
      )}

      {dragging ? (
        <div
          className="border-primary bg-accent/80 pointer-events-none fixed inset-4 z-50 grid place-items-center rounded-2xl border-2 border-dashed backdrop-blur-sm"
          aria-hidden
        >
          <div className="text-center">
            <FileUp className="text-primary mx-auto size-10" />
            <p className="mt-3 text-lg font-semibold">Drop to upload to {workspace.name}</p>
            <p className="text-muted-foreground text-sm">PDF, DOCX or TXT, up to {MAX_FILE_MB} MB each</p>
          </div>
        </div>
      ) : null}

      <DocumentDrawer documentId={openDoc} onClose={() => setParam('doc', null)} />
      <UploadTray workspaceId={workspace.id} />
    </div>
  )
}

function DocumentCard({ doc, onOpen }: { doc: DocumentItem; onOpen: () => void }) {
  return (
    <article className="bg-card hover:border-primary/40 group relative flex h-full flex-col rounded-xl border p-4 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <FileTypeIcon type={doc.file_type} />
        <div className="relative z-10">
          <DocumentActions doc={doc} />
        </div>
      </div>
      <h3 className="mt-3 line-clamp-2 text-[0.95rem] leading-snug font-semibold">
        {/* The whole card is clickable via this link's ::after; keyboard users tab to it. */}
        <button type="button" onClick={onOpen} className="text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-ring">
          {doc.title}
        </button>
      </h3>
      <p className="text-muted-foreground mt-1 text-xs">
        {[formatBytes(doc.size_bytes), pagesLabel(doc)].filter(Boolean).join(' · ')}
      </p>
      <div className="mt-auto flex items-center justify-between pt-4">
        <StatusBadge doc={doc} />
        <span className="text-muted-foreground text-xs">{timeAgo(doc.created_at)}</span>
      </div>
    </article>
  )
}

function DocumentTable({ docs, onOpen }: { docs: DocumentItem[]; onOpen: (id: string) => void }) {
  return (
    <div className="bg-card overflow-x-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead className="text-muted-foreground border-b text-left text-xs">
          <tr>
            <th className="px-4 py-2.5 font-medium">Name</th>
            <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Size</th>
            <th className="hidden px-4 py-2.5 font-medium md:table-cell">Added</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="w-12 px-2 py-2.5">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {docs.map((doc) => (
            <tr key={doc.id} className="hover:bg-muted/50">
              <td className="px-4 py-2.5">
                <button type="button" onClick={() => onOpen(doc.id)} className="flex items-center gap-3 text-left">
                  <FileTypeIcon type={doc.file_type} className="size-8" />
                  <span className="line-clamp-1 font-medium">{doc.title}</span>
                </button>
              </td>
              <td className="text-muted-foreground hidden px-4 py-2.5 whitespace-nowrap sm:table-cell">{formatBytes(doc.size_bytes)}</td>
              <td className="text-muted-foreground hidden px-4 py-2.5 whitespace-nowrap md:table-cell">{timeAgo(doc.created_at)}</td>
              <td className="px-4 py-2.5 whitespace-nowrap">
                <StatusBadge doc={doc} />
              </td>
              <td className="px-2 py-2.5">
                <DocumentActions doc={doc} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
