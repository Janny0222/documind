import { Fragment, type ReactNode } from 'react'
import type { Citation } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Renders model output as React elements - never via innerHTML - so text that came from an
 * uploaded document can't inject markup. Supports paragraphs, "-"/"1." lists, **bold**, and
 * [S1] citation markers (rendered as numbered buttons that open the source).
 */
export function AnswerText({
  text,
  citations,
  onCite,
  streaming = false,
}: {
  text: string
  citations: Citation[]
  onCite: (citation: Citation) => void
  streaming?: boolean
}) {
  const byMarker = new Map(citations.map((c) => [c.marker, c]))
  const order = citations.map((c) => c.marker)
  const blocks = toBlocks(text)
  return (
    <div className="space-y-3 text-[0.95rem] leading-relaxed">
      {blocks.map((block, i) =>
        block.kind === 'p' ? (
          <p key={i}>
            {inline(block.lines.join(' '), byMarker, order, onCite)}
            {streaming && i === blocks.length - 1 ? <Caret /> : null}
          </p>
        ) : (
          <ListTag key={i} ordered={block.kind === 'ol'}>
            {block.lines.map((line, j) => (
              <li key={j}>{inline(line, byMarker, order, onCite)}</li>
            ))}
          </ListTag>
        ),
      )}
      {streaming && blocks.length === 0 ? <Caret /> : null}
    </div>
  )
}

function Caret() {
  return <span className="bg-ai ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm motion-reduce:animate-none" aria-hidden />
}

function ListTag({ ordered, children }: { ordered: boolean; children: ReactNode }) {
  const className = cn('space-y-1.5 pl-5', ordered ? 'list-decimal' : 'list-disc')
  return ordered ? <ol className={className}>{children}</ol> : <ul className={className}>{children}</ul>
}

type Block = { kind: 'p' | 'ul' | 'ol'; lines: string[] }

function toBlocks(text: string): Block[] {
  const blocks: Block[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) {
      blocks.push({ kind: 'p', lines: [] })
      continue
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line)
    const kind: Block['kind'] = bullet ? 'ul' : numbered ? 'ol' : 'p'
    const content = bullet?.[1] ?? numbered?.[1] ?? line
    const last = blocks.at(-1)
    if (last && last.kind === kind && (kind !== 'p' || last.lines.length > 0)) last.lines.push(content)
    else blocks.push({ kind, lines: [content] })
  }
  return blocks.filter((b) => b.lines.length > 0)
}

function inline(
  text: string,
  byMarker: Map<string, Citation>,
  order: string[],
  onCite: (c: Citation) => void,
): ReactNode[] {
  // Split on **bold** and [S1] markers, keeping the delimiters.
  return text.split(/(\*\*[^*]+\*\*|\[S\d+\])/g).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>
    const marker = /^\[(S\d+)\]$/.exec(part)?.[1]
    if (marker) {
      const citation = byMarker.get(marker)
      if (!citation) return null // unverified marker (e.g. still streaming): hide rather than mislead
      const n = order.indexOf(marker) + 1
      return (
        <button
          key={i}
          type="button"
          onClick={() => onCite(citation)}
          className="bg-accent text-accent-foreground hover:bg-primary hover:text-primary-foreground mx-0.5 inline-grid h-[1.15rem] min-w-[1.15rem] -translate-y-0.5 place-items-center rounded px-1 align-middle text-[0.68rem] font-semibold transition-colors"
          aria-label={`Source ${n}: ${citation.document_title}${citation.page_number ? `, ${citation.page_unit} ${citation.page_number}` : ''}`}
        >
          {n}
        </button>
      )
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}
