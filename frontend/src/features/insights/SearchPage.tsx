import { Info, Search as SearchIcon, Sparkles } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { EmptyState, PageHeader, Tile } from '@/components/EmptyState'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { SourcePanel } from '@/features/ai/SourcePanel'
import { useCollections } from '@/features/documents/api'
import { FileTypeIcon } from '@/features/documents/components/bits'
import { type SearchHit, useSearch } from '@/features/insights/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import type { Citation, Scope } from '@/lib/types'
import { useMediaQuery } from '@/lib/use-media-query'
import { cn } from '@/lib/utils'

/** Hits open in the same source panel as AI citations: exact page, passage highlighted. */
const toCitation = (h: SearchHit): Citation => ({
  marker: 'S1',
  document_id: h.document_id,
  document_title: h.document_title,
  page_number: h.page_number,
  page_unit: h.page_unit,
  excerpt: h.text,
  chunk_id: h.chunk_id,
  char_start: h.char_start,
  char_end: h.char_end,
})

export function SearchPage() {
  const workspace = useCurrentWorkspace()
  const [params, setParams] = useSearchParams()
  const [input, setInput] = useState(params.get('q') ?? '')
  const query = params.get('q') ?? ''
  const collection = params.get('collection')
  const scope: Scope = collection ? { type: 'collection', id: collection } : { type: 'workspace' }
  const { data, isFetching, isError } = useSearch(workspace.id, query, scope)
  const { data: collections = [] } = useCollections(workspace.id)
  // A selection belongs to the query+scope it was made in, so a new search clears it without
  // an effect (derived during render).
  const resultsKey = `${query}|${collection ?? ''}`
  const [picked, setPicked] = useState<{ key: string; hit: SearchHit } | null>(null)
  const selected = picked?.key === resultsKey ? picked.hit : null
  const setSelected = (hit: SearchHit | null) => setPicked(hit ? { key: resultsKey, hit } : null)
  const wide = useMediaQuery('(min-width: 1280px)')

  // Debounce typing into the URL (shareable, back-button friendly).
  useEffect(() => {
    const next = input.trim()
    if (next === query) return
    const t = setTimeout(
      () =>
        setParams(
          (p) => {
            if (next) p.set('q', next)
            else p.delete('q')
            return p
          },
          { replace: true },
        ),
      350,
    )
    return () => clearTimeout(t)
  }, [input, query, setParams])

  const terms = query.toLowerCase().split(/\W+/).filter((t) => t.length > 2)

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="min-w-0">
        <PageHeader title="Search" description="Find passages by meaning and keywords. No AI answer, so it doesn't use your daily questions." />
        <div className="mb-5 flex flex-wrap gap-2">
          <label className="relative min-w-[14rem] flex-1">
            <span className="sr-only">Search your documents</span>
            <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden />
            <input
              type="search"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. notice period, payment terms, dental"
              className="border-input bg-card focus-visible:outline-ring h-11 w-full rounded-xl border pr-3 pl-9 focus-visible:outline-2"
            />
          </label>
          <label className="sr-only" htmlFor="search-scope">
            Search in
          </label>
          <select
            id="search-scope"
            value={collection ?? ''}
            onChange={(e) =>
              setParams(
                (p) => {
                  if (e.target.value) p.set('collection', e.target.value)
                  else p.delete('collection')
                  return p
                },
                { replace: true },
              )
            }
            className="border-input bg-card h-11 rounded-xl border px-3 text-sm"
          >
            <option value="">All documents</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                Collection: {c.name}
              </option>
            ))}
          </select>
        </div>

        {!query ? (
          <Tile>
            <EmptyState icon={SearchIcon} title="Search across every document">
              Search understands meaning, so “quitting” also finds passages about “resignation”. Exact names
              and numbers work too.
            </EmptyState>
          </Tile>
        ) : isFetching && !data ? (
          <div className="grid gap-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : isError ? (
          <Tile>
            <p className="text-destructive text-sm">Search failed. Try again in a moment.</p>
          </Tile>
        ) : (
          <>
            <p className="text-muted-foreground mb-3 flex items-center gap-2 text-sm" role="status">
              {data?.mode === 'hybrid' ? (
                <Sparkles className="text-primary size-4" aria-hidden />
              ) : (
                <Info className="size-4" aria-hidden />
              )}
              {data?.hits.length ?? 0} passage{data?.hits.length === 1 ? '' : 's'}
              {data?.mode === 'keyword' ? ' · keyword matches only (AI processing is off for this workspace)' : ''}
            </p>
            {!data?.hits.length ? (
              <Tile>
                <EmptyState icon={SearchIcon} title="No passages match">
                  Try other words, or search all documents.
                </EmptyState>
              </Tile>
            ) : (
              <ul className="grid gap-3">
                {data.hits.map((h) => (
                  <li key={h.chunk_id}>
                    <button
                      type="button"
                      onClick={() => setSelected(h)}
                      aria-pressed={selected?.chunk_id === h.chunk_id}
                      className={cn(
                        'bg-card hover:border-primary/40 w-full rounded-xl border p-4 text-left transition-colors',
                        selected?.chunk_id === h.chunk_id && 'border-primary ring-primary/20 ring-2',
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <FileTypeIcon type={h.file_type} className="size-7" />
                        <span className="truncate text-sm font-medium">{h.document_title}</span>
                        {h.page_number ? (
                          <span className="text-muted-foreground shrink-0 text-xs">
                            · {h.page_unit} {h.page_number}
                          </span>
                        ) : null}
                      </span>
                      <span className="text-muted-foreground mt-2 line-clamp-3 block text-sm leading-relaxed">
                        <Highlighted text={h.text} terms={terms} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {wide ? (
        <div className="sticky top-20 h-[calc(100dvh-7rem)]">
          {selected ? (
            <SourcePanel citation={toCitation(selected)} onClose={() => setSelected(null)} />
          ) : (
            <div className="text-muted-foreground grid h-full place-items-center rounded-xl border border-dashed p-6 text-center text-sm">
              Select a result to read it in context.
            </div>
          )}
        </div>
      ) : (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent className="w-full p-3 sm:max-w-md">
            <SheetTitle className="sr-only">Passage</SheetTitle>
            {selected ? <SourcePanel citation={toCitation(selected)} onClose={() => setSelected(null)} /> : null}
          </SheetContent>
        </Sheet>
      )}
    </div>
  )
}

/** Bold the query's words inside a snippet - built from React text nodes, never HTML. */
function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>
  const pattern = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return (
    <>
      {text.split(pattern).map((part, i) =>
        terms.includes(part.toLowerCase()) ? (
          <mark key={i} className="text-foreground rounded bg-transparent font-semibold">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}
