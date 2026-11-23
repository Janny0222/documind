import { ArrowUp, Sparkles } from 'lucide-react'
import { useId, useState } from 'react'
import { useNavigate } from 'react-router'
import { wsPath } from '@/layouts/nav'
import { cn } from '@/lib/utils'

const suggestions = [
  'Summarize this document',
  'What are the key dates and deadlines?',
  'Which document mentions the cancellation policy?',
]

/**
 * The hero of the dashboard and the product's signature: the only surface that carries the
 * AI gradient on the home screen. It hands the question to the AI workspace.
 */
export function AskBar({ workspaceId }: { workspaceId: string }) {
  const [value, setValue] = useState('')
  const navigate = useNavigate()
  const inputId = useId()
  const question = value.trim()

  const submit = (q: string) => {
    if (!q) return
    navigate(`${wsPath(workspaceId, 'ask')}?q=${encodeURIComponent(q)}`)
  }

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit(question)
        }}
        className="ring-ai group flex items-center gap-3 rounded-2xl py-2 pr-2 pl-4 shadow-[var(--shadow-lift)] transition-shadow focus-within:shadow-[0_0_0_4px_color-mix(in_oklch,var(--ai-from)_18%,transparent),var(--shadow-lift)]"
      >
        <Sparkles className="text-primary size-5 shrink-0" aria-hidden />
        <label htmlFor={inputId} className="sr-only">
          Ask your documents a question
        </label>
        <input
          id={inputId}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask your documents anything…"
          autoComplete="off"
          className="placeholder:text-muted-foreground h-11 min-w-0 flex-1 bg-transparent text-base outline-none focus-visible:outline-none"
        />
        <button
          type="submit"
          disabled={!question}
          aria-label="Ask"
          className={cn(
            'grid size-10 shrink-0 place-items-center rounded-xl text-white transition-opacity',
            'bg-ai disabled:opacity-35',
          )}
        >
          <ArrowUp className="size-5" aria-hidden />
        </button>
      </form>
      <ul className="mt-3 flex flex-wrap gap-2" aria-label="Example questions">
        {suggestions.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => setValue(s)}
              className="bg-card text-muted-foreground hover:text-foreground hover:border-primary/40 rounded-full border px-3 py-1 text-[0.8rem] transition-colors"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
