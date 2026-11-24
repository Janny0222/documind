import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  Check,
  Copy,
  Loader2,
  MessageSquarePlus,
  PanelLeft,
  RotateCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { useMediaQuery } from '@/lib/use-media-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  aiKeys,
  askPath,
  regeneratePath,
  useAiStatus,
  useConversation,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useUpdateConversation,
} from '@/features/ai/api'
import { AnswerText } from '@/features/ai/AnswerText'
import { SourcePanel } from '@/features/ai/SourcePanel'
import { streamAnswer } from '@/features/ai/stream'
import { useCollections, useDocument } from '@/features/documents/api'
import { useGrantAiConsent } from '@/features/workspaces/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { toApiError } from '@/lib/api'
import { atLeast, type ChatMessage, type Citation, type ConversationDetail, type Scope } from '@/lib/types'
import { cn } from '@/lib/utils'

interface LiveAnswer {
  /** The conversation this answer streams into. */
  conversationId: string
  question: string
  text: string
  citations: Citation[]
  suggestions: string[]
  retrieval: { documents: number; passages: number } | null
  error: string | null
  regenerating: boolean
  /** streaming: show the live bubble. finished: the stored message took over; keep suggestions/errors. */
  phase: 'streaming' | 'finished'
}

export function AskPage() {
  const workspace = useCurrentWorkspace()
  const { conversationId } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: status } = useAiStatus(workspace.id)
  const { data: conversation, isPending: loadingConversation } = useConversation(workspace.id, conversationId)
  const create = useCreateConversation(workspace.id)
  const updateConversation = useUpdateConversation(workspace.id)

  const [draftScope, setDraftScope] = useState<Scope>(() => {
    const doc = params.get('doc')
    return doc ? { type: 'documents', ids: [doc] } : { type: 'workspace' }
  })
  const scope = conversation?.scope ?? draftScope
  const [input, setInput] = useState('')
  const [live, setLive] = useState<LiveAnswer | null>(null)
  const [source, setSource] = useState<Citation | null>(null)
  const [railOpen, setRailOpen] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const streaming = live?.phase === 'streaming' && live.error === null
  const wide = useMediaQuery('(min-width: 1280px)')

  const canAsk = !!status?.configured && !!status.consent && status.questions_left_today > 0

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [conversation?.messages.length, live?.text])

  // Clear the source panel and live answer when switching conversations. The first question of a
  // new conversation also changes conversationId (/ask -> /ask/:id), and on a slow device this
  // effect can run after that answer has started streaming - so keep an answer that belongs here.
  useEffect(() => {
    setSource(null)
    setLive((l) => (l && l.conversationId === conversationId ? l : null))
  }, [conversationId])

  async function run(conversation: string, path: string, body: unknown, question: string, regenerating = false) {
    const controller = new AbortController()
    abort.current = controller
    setLive({
      conversationId: conversation,
      question,
      text: '',
      citations: [],
      suggestions: [],
      retrieval: null,
      error: null,
      regenerating,
      phase: 'streaming',
    })
    try {
      await streamAnswer(
        path,
        body,
        {
          onRetrieval: (retrieval) => setLive((l) => l && { ...l, retrieval }),
          onToken: (t) => setLive((l) => l && { ...l, text: l.text + t }),
          onCitations: (citations) => setLive((l) => l && { ...l, citations }),
          onSuggestions: (suggestions) => setLive((l) => l && { ...l, suggestions }),
          onError: (e) => setLive((l) => l && { ...l, error: e.message }),
          onDone: () => undefined,
        },
        controller.signal,
      )
      await qc.invalidateQueries({ queryKey: aiKeys.conversation(workspace.id, conversation) })
      void qc.invalidateQueries({ queryKey: aiKeys.conversations(workspace.id) })
      void qc.invalidateQueries({ queryKey: aiKeys.status(workspace.id) })
      // Keep suggestions/errors visible after the stored message replaces the live one.
      setLive((l) => (l && (l.error || l.suggestions.length) ? { ...l, phase: 'finished' } : null))
    } catch (err) {
      if (controller.signal.aborted) {
        setLive(null)
        void qc.invalidateQueries({ queryKey: aiKeys.conversation(workspace.id, conversation) })
        return
      }
      const e = toApiError(err)
      setLive((l) => l && { ...l, error: e.message, phase: 'finished' })
      void qc.invalidateQueries({ queryKey: aiKeys.status(workspace.id) })
    } finally {
      abort.current = null
    }
  }

  async function send(text: string) {
    const question = text.trim()
    if (!question || streaming) return
    setInput('')
    let id = conversationId
    if (!id) {
      try {
        const c = await create.mutateAsync({ scope: draftScope })
        id = c.id
        // Seed the cache so the new conversation renders immediately, then update the URL.
        qc.setQueryData<ConversationDetail>(aiKeys.conversation(workspace.id, c.id), { ...c, messages: [] })
        navigate(wsPath(workspace.id, `ask/${c.id}`), { replace: true })
      } catch (err) {
        toast.error(toApiError(err).message)
        setInput(question)
        return
      }
    }
    // Show the question right away (the server stores it first, too).
    qc.setQueryData<ConversationDetail>(aiKeys.conversation(workspace.id, id), (d) =>
      d ? { ...d, messages: [...d.messages, optimisticUser(question)] } : d,
    )
    await run(id, askPath(workspace.id, id), { content: question }, question)
  }

  async function regenerate(message: ChatMessage) {
    if (!conversationId || streaming) return
    qc.setQueryData<ConversationDetail>(aiKeys.conversation(workspace.id, conversationId), (d) =>
      d ? { ...d, messages: d.messages.filter((m) => m.id !== message.id) } : d,
    )
    await run(conversationId, regeneratePath(workspace.id, conversationId, message.id), undefined, '', true)
  }

  // Dashboard / command palette hand over a question via ?q=. Ask it once.
  const handedOver = useRef(false)
  useEffect(() => {
    const q = params.get('q')
    if (q && !handedOver.current && !conversationId && canAsk) {
      handedOver.current = true
      setParams({}, { replace: true })
      void send(q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when ready
  }, [canAsk])

  const messages = conversation?.messages ?? []
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const showLive = live?.phase === 'streaming'

  return (
    <div className="-mt-2 grid h-[calc(100dvh-9.5rem)] grid-cols-1 gap-4 md:h-[calc(100dvh-7.5rem)] lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_22rem]">
      {/* Conversation history: a rail on desktop, a sheet on smaller screens. */}
      <div className="hidden min-h-0 lg:block">
        <ConversationRail activeId={conversationId} />
      </div>
      <Sheet open={railOpen} onOpenChange={setRailOpen}>
        <SheetContent side="left" className="w-72 p-3">
          <SheetTitle className="sr-only">Conversations</SheetTitle>
          <ConversationRail activeId={conversationId} onNavigate={() => setRailOpen(false)} />
        </SheetContent>
      </Sheet>

      <section className="flex min-h-0 flex-col" aria-label="Conversation">
        <header className="mb-3 flex items-center gap-2">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setRailOpen(true)} aria-label="Show conversations">
            <PanelLeft aria-hidden />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">{conversation?.title ?? 'New conversation'}</h1>
          <ScopePicker
            scope={scope}
            onChange={(s) =>
              conversationId
                ? updateConversation.mutate({ id: conversationId, scope: s }, { onError: (e) => toast.error(toApiError(e).message) })
                : setDraftScope(s)
            }
          />
        </header>

        <StatusBanner />

        <div className="min-h-0 flex-1 overflow-y-auto pr-1" aria-live="polite">
          {conversationId && loadingConversation ? (
            <div className="grid gap-4 pt-4">
              <Skeleton className="ml-auto h-10 w-1/2 rounded-2xl" />
              <Skeleton className="h-24 w-3/4 rounded-2xl" />
            </div>
          ) : messages.length === 0 && !showLive ? (
            <EmptyThread scope={scope} onPick={(q) => setInput(q)} onAskEverything={() => setDraftScope({ type: 'workspace' })} />
          ) : (
            <ol className="space-y-6 pb-4">
              {messages.map((m) => (
                <li key={m.id}>
                  {m.role === 'user' ? (
                    <UserBubble text={m.content} />
                  ) : (
                    <AssistantMessage
                      message={m}
                      onCite={setSource}
                      onRegenerate={m.id === lastAssistant?.id && !streaming ? () => void regenerate(m) : undefined}
                    />
                  )}
                </li>
              ))}
              {live && showLive ? (
                <li>
                  <div className="space-y-2">
                    {!live.retrieval && !live.error ? (
                      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
                        <Search className="size-4 animate-pulse" aria-hidden /> Searching your documents…
                      </p>
                    ) : live.retrieval && !live.text && !live.error ? (
                      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
                        <Sparkles className="text-primary size-4" aria-hidden /> Reading {live.retrieval.passages} passages from{' '}
                        {live.retrieval.documents} document{live.retrieval.documents === 1 ? '' : 's'}…
                      </p>
                    ) : null}
                    {live.text ? (
                      <div className="ring-ai rounded-2xl rounded-tl-md p-4">
                        <AnswerText text={live.text} citations={live.citations} onCite={setSource} streaming={!live.error} />
                      </div>
                    ) : null}
                  </div>
                </li>
              ) : null}
              {live?.error ? (
                <li role="alert" className="border-destructive/30 bg-destructive/5 text-destructive rounded-lg border px-4 py-3 text-sm">
                  {live.error}
                </li>
              ) : null}
              {live && live.suggestions.length > 0 && !streaming ? (
                <li>
                  <p className="text-muted-foreground mb-2 text-xs">Follow-up questions</p>
                  <div className="flex flex-wrap gap-2">
                    {live.suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => void send(s)}
                        disabled={!canAsk}
                        className="bg-card hover:border-primary/40 rounded-full border px-3 py-1.5 text-left text-sm transition-colors disabled:opacity-50"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </li>
              ) : null}
            </ol>
          )}
          <div ref={bottom} />
        </div>

        <Composer
          value={input}
          onChange={setInput}
          onSend={() => void send(input)}
          onStop={() => abort.current?.abort()}
          streaming={streaming}
          disabled={!canAsk}
          questionsLeft={status?.questions_left_today}
        />
      </section>

      {/* Sources: a column on wide screens, a sheet otherwise. */}
      {/* Mounted only when wide, so narrow screens don't render (and fetch for) a hidden panel. */}
      {wide ? (
      <div className="min-h-0">
        {source ? (
          <SourcePanel citation={source} onClose={() => setSource(null)} />
        ) : (
          <div className="text-muted-foreground grid h-full place-items-center rounded-xl border border-dashed p-6 text-center text-sm">
            Select a numbered citation in an answer to see the exact passage it came from.
          </div>
        )}
      </div>
      ) : null}
      <Sheet open={!!source && !wide} onOpenChange={(o) => !o && setSource(null)}>
        <SheetContent className="w-full p-3 sm:max-w-md">
          <SheetTitle className="sr-only">Source</SheetTitle>
          {source ? <SourcePanel citation={source} onClose={() => setSource(null)} /> : null}
        </SheetContent>
      </Sheet>
    </div>
  )
}

const optimisticUser = (content: string): ChatMessage => ({
  id: `local-${crypto.randomUUID()}`,
  role: 'user',
  content,
  status: 'complete',
  created_at: new Date().toISOString(),
  citations: [],
})

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="bg-accent text-accent-foreground max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 whitespace-pre-wrap">{text}</p>
    </div>
  )
}

function AssistantMessage({
  message,
  onCite,
  onRegenerate,
}: {
  message: ChatMessage
  onCite: (c: Citation) => void
  onRegenerate?: () => void
}) {
  const [copied, setCopied] = useState(false)
  if (message.status === 'failed' && !message.content) {
    return (
      <p className="text-muted-foreground text-sm">
        This answer didn&apos;t finish.{' '}
        {onRegenerate ? (
          <button type="button" onClick={onRegenerate} className="text-primary font-medium hover:underline">
            Try again
          </button>
        ) : null}
      </p>
    )
  }
  const notFound = message.status === 'not_found'
  return (
    <div>
      <div className={cn('rounded-2xl rounded-tl-md p-4', notFound ? 'bg-muted text-muted-foreground' : 'ring-ai')}>
        <AnswerText text={message.content} citations={message.citations} onCite={onCite} />
      </div>
      {message.citations.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {message.citations.map((c, i) => (
            <button
              key={c.marker}
              type="button"
              onClick={() => onCite(c)}
              className="bg-card hover:border-primary/40 flex max-w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors"
            >
              <span className="bg-accent text-accent-foreground grid size-5 shrink-0 place-items-center rounded font-semibold">{i + 1}</span>
              <span className="truncate">
                {c.document_title}
                {c.page_number ? <span className="text-muted-foreground"> · {c.page_unit} {c.page_number}</span> : null}
                {!c.document_id ? <span className="text-muted-foreground"> (deleted)</span> : null}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="mt-1.5 flex gap-1">
        <Button
          variant="ghost"
          size="xs"
          onClick={async () => {
            await navigator.clipboard.writeText(message.content.replace(/\[S\d+\]/g, ''))
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />} {copied ? 'Copied' : 'Copy'}
        </Button>
        {onRegenerate ? (
          <Button variant="ghost" size="xs" onClick={onRegenerate}>
            <RotateCcw aria-hidden /> Regenerate
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  disabled,
  questionsLeft,
}: {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  onStop: () => void
  streaming: boolean
  disabled: boolean
  questionsLeft: number | undefined
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      onSend()
    }
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSend()
      }}
      className="mt-3"
    >
      <div className="ring-ai flex items-end gap-2 rounded-2xl p-2 shadow-[var(--shadow-soft)]">
        <label htmlFor="ask-input" className="sr-only">
          Ask a question about your documents
        </label>
        <textarea
          id="ask-input"
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={disabled ? 'Asking is unavailable right now' : 'Ask a follow-up or a new question…'}
          className="placeholder:text-muted-foreground max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none [field-sizing:content] focus-visible:outline-none disabled:opacity-60"
          maxLength={2000}
        />
        {streaming ? (
          <Button type="button" size="icon" variant="outline" onClick={onStop} aria-label="Stop generating" className="rounded-xl">
            <Square className="fill-current" aria-hidden />
          </Button>
        ) : (
          <button
            type="submit"
            disabled={disabled || !value.trim()}
            aria-label="Ask"
            className="bg-ai grid size-10 shrink-0 place-items-center rounded-xl text-white disabled:opacity-35"
          >
            <ArrowUp className="size-5" aria-hidden />
          </button>
        )}
      </div>
      <p className="text-muted-foreground mt-1.5 px-2 text-xs">
        Answers come only from your documents and can still be wrong. Check the sources.
        {questionsLeft !== undefined ? ` ${questionsLeft} questions left today.` : ''}
      </p>
    </form>
  )
}

function ScopePicker({ scope, onChange }: { scope: Scope; onChange: (s: Scope) => void }) {
  const workspace = useCurrentWorkspace()
  const { data: collections = [] } = useCollections(workspace.id)
  const docTitle = useScopedDocumentTitle(scope)
  const value = scope.type === 'collection' ? `c:${scope.id}` : scope.type === 'documents' ? 'docs' : 'all'
  const docsLabel =
    scope.type !== 'documents' ? '' : scope.ids.length > 1 ? `${scope.ids.length} documents` : docTitle ? `Only: ${docTitle}` : 'One document'
  return (
    <>
      <label htmlFor="scope" className="sr-only">
        Search in
      </label>
      <select
        id="scope"
        value={value}
        onChange={(e) => {
          const v = e.target.value
          if (v === 'all') onChange({ type: 'workspace' })
          else if (v.startsWith('c:')) onChange({ type: 'collection', id: v.slice(2) })
        }}
        className="border-input bg-card h-9 max-w-[9rem] min-w-0 shrink rounded-md border px-2 text-sm sm:max-w-[12rem]"
      >
        <option value="all">All documents</option>
        {collections.map((c) => (
          <option key={c.id} value={`c:${c.id}`}>
            Collection: {c.name}
          </option>
        ))}
        {scope.type === 'documents' ? <option value="docs">{docsLabel}</option> : null}
      </select>
    </>
  )
}

function StatusBanner() {
  const workspace = useCurrentWorkspace()
  const { data: status } = useAiStatus(workspace.id)
  const grant = useGrantAiConsent(workspace.id)
  const qc = useQueryClient()
  if (!status) return null
  let message: string | null = null
  let action = null
  if (!status.configured) message = "AI isn't configured on this server yet, so questions can't be answered."
  else if (!status.consent) {
    message = atLeast(workspace.role, 'admin')
      ? 'To answer questions, document passages are sent to Google Gemini. On the free tier Google may use them to improve its products. Allow this for the workspace?'
      : 'A workspace admin needs to allow AI processing before anyone can ask questions.'
    if (atLeast(workspace.role, 'admin')) {
      action = (
        <Button
          size="sm"
          variant="outline"
          disabled={grant.isPending}
          onClick={() =>
            grant.mutate(undefined, {
              onSuccess: () => {
                toast.success('AI processing allowed. Documents are being prepared for questions.')
                void qc.invalidateQueries({ queryKey: aiKeys.status(workspace.id) })
              },
              onError: (e) => toast.error(toApiError(e).message),
            })
          }
        >
          {grant.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null} Allow AI processing
        </Button>
      )
    }
  } else if (status.questions_left_today === 0) {
    message = `You've used all ${status.daily_limit} questions for today. The limit resets at midnight UTC.`
  }
  if (!message) return null
  return (
    <div className="border-warning/30 bg-warning/5 mb-3 flex flex-wrap items-center gap-3 rounded-xl border p-3 text-sm" role="status">
      <ShieldAlert className="text-warning size-5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">{message}</p>
      {action}
    </div>
  )
}

const SINGLE_DOC_EXAMPLES = ['What are the key dates and deadlines?', 'What are the main rules or obligations?', 'Who are the parties involved?']
const WORKSPACE_EXAMPLES = ['What are the deadlines and notice periods?', 'Which document mentions cancellation?', 'How many vacation days do employees get?']

/** Title of the one document a "documents" scope points at (null while loading or for other scopes). */
function useScopedDocumentTitle(scope: Scope): string | null {
  const workspace = useCurrentWorkspace()
  const id = scope.type === 'documents' && scope.ids.length === 1 ? (scope.ids[0] ?? null) : null
  const { data } = useDocument(workspace.id, id)
  return id && data ? data.title : null
}

function EmptyThread({ scope, onPick, onAskEverything }: { scope: Scope; onPick: (q: string) => void; onAskEverything: () => void }) {
  const docTitle = useScopedDocumentTitle(scope)
  const single = scope.type === 'documents' && scope.ids.length === 1
  const examples = single ? SINGLE_DOC_EXAMPLES : WORKSPACE_EXAMPLES
  return (
    <div className="grid h-full place-items-center px-4 text-center">
      <div className="max-w-md">
        <Sparkles className="text-primary mx-auto size-8" aria-hidden />
        <h2 className="mt-3 text-xl font-semibold break-words">
          {single ? (docTitle ? `Ask about “${docTitle}”` : 'Ask about this document') : 'Ask your documents'}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {single
            ? 'Answers use only this document, and every claim links to the passage it came from.'
            : 'Answers use only the documents in the selected scope, and every claim links to the passage it came from.'}
        </p>
        {scope.type === 'documents' ? (
          <button type="button" onClick={onAskEverything} className="text-primary mt-2 text-sm font-medium hover:underline">
            Ask all documents instead
          </button>
        ) : null}
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {examples.map((q) => (
            <button key={q} type="button" onClick={() => onPick(q)} className="bg-card hover:border-primary/40 rounded-full border px-3 py-1.5 text-sm transition-colors">
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function ConversationRail({ activeId, onNavigate }: { activeId?: string; onNavigate?: () => void }) {
  const workspace = useCurrentWorkspace()
  const { data: conversations, isPending } = useConversations(workspace.id)
  const del = useDeleteConversation(workspace.id)
  const navigate = useNavigate()
  return (
    <nav aria-label="Conversations" className="flex h-full min-h-0 flex-col">
      <Button asChild className="mb-3 w-full justify-start" onClick={onNavigate}>
        <Link to={wsPath(workspace.id, 'ask')}>
          <MessageSquarePlus aria-hidden /> New conversation
        </Link>
      </Button>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        {isPending ? (
          <div className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : !conversations?.length ? (
          <p className="text-muted-foreground px-2 text-sm">Your conversations appear here. Only you can see them.</p>
        ) : (
          <ul className="grid gap-0.5">
            {conversations.map((c) => (
              <li key={c.id} className="group relative min-w-0">
                <Link
                  to={wsPath(workspace.id, `ask/${c.id}`)}
                  onClick={onNavigate}
                  aria-current={c.id === activeId ? 'page' : undefined}
                  className={cn(
                    'block truncate rounded-md py-1.5 pr-8 pl-2.5 text-sm transition-colors',
                    c.id === activeId ? 'bg-accent text-accent-foreground font-medium' : 'hover:bg-muted text-muted-foreground hover:text-foreground',
                  )}
                >
                  {c.title}
                </Link>
                <button
                  type="button"
                  aria-label={`Delete conversation ${c.title}`}
                  onClick={() =>
                    del.mutate(c.id, {
                      onSuccess: () => c.id === activeId && navigate(wsPath(workspace.id, 'ask'), { replace: true }),
                      onError: (e) => toast.error(toApiError(e).message),
                    })
                  }
                  className="text-muted-foreground hover:text-destructive absolute top-1/2 right-1 grid size-6 -translate-y-1/2 place-items-center rounded opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </nav>
  )
}
