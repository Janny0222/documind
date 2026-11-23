import { Check, FileUp, FlaskConical, Loader2, ShieldCheck, Upload, UserPlus, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { EmptyState, Tile } from '@/components/EmptyState'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useMe } from '@/features/auth/api'
import { AskBar } from '@/features/dashboard/AskBar'
import { useDocuments } from '@/features/documents/api'
import { FileTypeIcon, StatusBadge } from '@/features/documents/components/bits'
import { timeAgo } from '@/features/documents/format'
import { useGrantAiConsent, useMembers } from '@/features/workspaces/api'
import { TryDemoButton } from '@/features/workspaces/components/DemoEntry'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { initials } from '@/lib/format'
import { toApiError } from '@/lib/api'
import { atLeast } from '@/lib/types'
import { cn } from '@/lib/utils'

function greeting(date = new Date()) {
  const h = date.getHours()
  return h < 5 ? 'Working late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function DashboardPage() {
  const { data: user } = useMe()
  const workspace = useCurrentWorkspace()
  const firstName = user?.display_name.split(/\s+/)[0] ?? ''

  return (
    <div className="grid gap-4 md:gap-5 lg:grid-cols-12">
      <section aria-labelledby="greeting" className="lg:col-span-8 lg:py-4 lg:pr-6">
        <p className="text-muted-foreground text-sm">{workspace.name}</p>
        <h1 id="greeting" className="mt-1 text-[1.9rem] leading-tight font-bold md:text-[2.4rem]">
          {greeting()}, {firstName}.
        </h1>
        <p className="text-muted-foreground mt-2 mb-7 max-w-xl">
          Ask a question and DocuMind answers from your documents, with a link to every passage it
          used.
        </p>
        <AskBar workspaceId={workspace.id} />
      </section>

      {workspace.is_demo ? <DemoIntro className="lg:col-span-4" /> : <SetupChecklist className="lg:col-span-4" />}

      <Tile className="lg:col-span-7" aria-labelledby="recent-docs">
        <div className="flex items-center justify-between">
          <h2 id="recent-docs" className="text-base font-semibold">
            Recent documents
          </h2>
          <Link to={wsPath(workspace.id, 'documents')} className="text-primary text-sm font-medium hover:underline">
            All documents
          </Link>
        </div>
        <RecentDocuments />
      </Tile>

      <WorkspaceCard className="lg:col-span-5" />
    </div>
  )
}

const DEMO_QUESTIONS = [
  'How many vacation days do employees get?',
  'What happens if the client pays an invoice late?',
  'Which Brightdesk plans include single sign-on?',
]

function DemoIntro({ className }: { className?: string }) {
  const workspace = useCurrentWorkspace()
  return (
    <Tile className={className} aria-labelledby="demo-title">
      <h2 id="demo-title" className="flex items-center gap-2 text-base font-semibold">
        <FlaskConical className="text-primary size-4" aria-hidden />
        Questions to try
      </h2>
      <p className="text-muted-foreground mt-1 text-sm">
        Three sample documents: a staff handbook, a client agreement and a product FAQ.
      </p>
      <ul className="mt-4 grid gap-2">
        {DEMO_QUESTIONS.map((q) => (
          <li key={q}>
            <Link
              to={`${wsPath(workspace.id, 'ask')}?q=${encodeURIComponent(q)}`}
              className="hover:border-primary/40 block rounded-lg border px-3 py-2 text-sm transition-colors"
            >
              {q}
            </Link>
          </li>
        ))}
      </ul>
    </Tile>
  )
}

function SetupChecklist({ className }: { className?: string }) {
  const workspace = useCurrentWorkspace()
  const grant = useGrantAiConsent(workspace.id)
  const isAdmin = atLeast(workspace.role, 'admin')
  const { data: docs } = useDocuments(workspace.id, { sort: 'newest' }) // same query as Recent documents: one request
  const hasDocuments = (docs?.counts.all ?? 0) > 0

  const steps: { done: boolean; title: string; body: ReactNode; action?: ReactNode; icon: typeof Upload }[] = [
    {
      icon: ShieldCheck,
      done: workspace.ai_consent,
      title: 'Allow AI processing',
      body: isAdmin
        ? 'Document text is sent to Google Gemini to build answers. Confirm this before indexing.'
        : 'A workspace admin needs to confirm that documents may be processed by Google Gemini.',
      action:
        isAdmin && !workspace.ai_consent ? (
          <Button
            size="sm"
            variant="outline"
            disabled={grant.isPending}
            onClick={() =>
              grant.mutate(undefined, {
                onSuccess: () => toast.success('AI processing allowed for this workspace'),
                onError: (e) => toast.error(toApiError(e).message),
              })
            }
          >
            {grant.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Allow
          </Button>
        ) : null,
    },
    {
      icon: Upload,
      done: hasDocuments,
      title: 'Upload your first document',
      body: 'PDF, DOCX or TXT up to 10 MB each.',
      action: atLeast(workspace.role, 'member') ? (
        <Button size="sm" variant="outline" asChild>
          <Link to={wsPath(workspace.id, 'documents')}>Upload</Link>
        </Button>
      ) : null,
    },
    // Personal workspaces can't have members, so that step only exists for team workspaces.
    ...(workspace.is_personal ? [] : [{
      icon: UserPlus,
      done: workspace.member_count > 1,
      title: 'Invite your team',
      body: 'Share an invite link so teammates can ask the same documents.',
      action:
        isAdmin && workspace.member_count <= 1 ? (
          <Button size="sm" variant="outline" asChild>
            <Link to={wsPath(workspace.id, 'settings/members')}>Invite</Link>
          </Button>
        ) : null,
    }]),
  ]
  const doneCount = steps.filter((s) => s.done).length

  return (
    <Tile className={className} aria-labelledby="setup-title">
      <div className="flex items-baseline justify-between">
        <h2 id="setup-title" className="text-base font-semibold">
          Set up this workspace
        </h2>
        <span className="text-muted-foreground text-sm">
          {doneCount} of {steps.length} done
        </span>
      </div>
      <ol className="mt-4 grid gap-1">
        {steps.map((step, i) => (
          <li key={step.title} className="flex gap-3 rounded-lg py-2.5">
            <span
              className={cn(
                'mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border text-xs font-semibold',
                step.done ? 'bg-success border-success text-white' : 'text-muted-foreground',
              )}
              aria-hidden
            >
              {step.done ? <Check className="size-3.5" /> : i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className={cn('text-sm font-medium', step.done && 'text-muted-foreground line-through decoration-1')}>
                {step.title}
                <span className="sr-only">{step.done ? ' (done)' : ' (to do)'}</span>
              </p>
              {!step.done ? <p className="text-muted-foreground mt-0.5 text-[0.8rem]">{step.body}</p> : null}
            </div>
            {!step.done && step.action ? <div className="shrink-0">{step.action}</div> : null}
          </li>
        ))}
      </ol>
    </Tile>
  )
}

const roleLabel = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' } as const

function WorkspaceCard({ className }: { className?: string }) {
  const workspace = useCurrentWorkspace()
  const { data: members, isPending } = useMembers(workspace.id)

  return (
    <Tile className={className} aria-labelledby="ws-card">
      <div className="flex items-center justify-between">
        <h2 id="ws-card" className="text-base font-semibold">
          People
        </h2>
        <Link to={wsPath(workspace.id, 'settings/members')} className="text-primary text-sm font-medium hover:underline">
          Manage
        </Link>
      </div>
      <p className="text-muted-foreground mt-1 text-sm">
        You&apos;re {workspace.role === 'admin' || workspace.role === 'owner' ? 'an' : 'a'}{' '}
        {roleLabel[workspace.role].toLowerCase()} of {workspace.name}.
      </p>
      <ul className="mt-4 grid gap-3">
        {isPending
          ? [0, 1].map((i) => (
              <li key={i} className="flex items-center gap-3">
                <Skeleton className="size-8 rounded-full" />
                <Skeleton className="h-4 w-40" />
              </li>
            ))
          : members?.slice(0, 5).map((m) => (
              <li key={m.user_id} className="flex items-center gap-3">
                <Avatar className="size-8">
                  <AvatarFallback className="bg-accent text-accent-foreground text-xs font-semibold">
                    {initials(m.display_name)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{m.display_name}</p>
                  <p className="text-muted-foreground truncate text-xs">{m.email}</p>
                </div>
                <span className="text-muted-foreground text-xs">{roleLabel[m.role]}</span>
              </li>
            ))}
      </ul>
      {members && members.length > 5 ? (
        <p className="text-muted-foreground mt-3 text-sm">and {members.length - 5} more</p>
      ) : null}
      {members && members.length <= 1 ? (
        <p className="text-muted-foreground mt-4 flex items-center gap-2 text-sm">
          <Users className="size-4" aria-hidden /> Just you so far.
        </p>
      ) : null}
    </Tile>
  )
}

function RecentDocuments() {
  const workspace = useCurrentWorkspace()
  const { data, isPending } = useDocuments(workspace.id, { sort: 'newest' })
  if (isPending) {
    return (
      <div className="mt-4 grid gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 rounded-lg" />
        ))}
      </div>
    )
  }
  const recent = data?.items.slice(0, 5) ?? []
  if (recent.length === 0) {
    return (
      <EmptyState icon={FileUp} title="No documents yet" className="py-10" action={
        <div className="flex flex-wrap justify-center gap-2">
          {atLeast(workspace.role, 'member') ? (
            <Button variant="outline" asChild>
              <Link to={wsPath(workspace.id, 'documents')}>Upload documents</Link>
            </Button>
          ) : null}
          <TryDemoButton variant="ghost" />
        </div>
      }>
        PDFs, Word files and plain text appear here once they&apos;re uploaded.
      </EmptyState>
    )
  }
  return (
    <ul className="mt-3 divide-y">
      {recent.map((doc) => (
        <li key={doc.id}>
          <Link
            to={`${wsPath(workspace.id, 'documents')}?doc=${doc.id}`}
            className="hover:bg-muted/50 -mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5"
          >
            <FileTypeIcon type={doc.file_type} className="size-9" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{doc.title}</span>
              <span className="text-muted-foreground text-xs">{timeAgo(doc.created_at)}</span>
            </span>
            <StatusBadge doc={doc} />
          </Link>
        </li>
      ))}
    </ul>
  )
}
