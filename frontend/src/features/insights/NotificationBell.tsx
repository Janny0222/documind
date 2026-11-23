import { AlertCircle, Bell, CheckCircle2, Loader2, UserPlus, Users } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { timeAgo } from '@/features/documents/format'
import { type Notification, useAcceptInvitationById, useMarkRead, useNotifications } from '@/features/insights/api'
import { toApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

const icons = {
  document_ready: { icon: CheckCircle2, className: 'text-success' },
  document_failed: { icon: AlertCircle, className: 'text-destructive' },
  invitation: { icon: UserPlus, className: 'text-primary' },
  member_joined: { icon: Users, className: 'text-primary' },
} as const

export function NotificationBell() {
  const { data } = useNotifications()
  const markRead = useMarkRead()
  const [open, setOpen] = useState(false)
  const unread = data?.unread ?? 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}>
          <Bell aria-hidden />
          {unread > 0 ? (
            <span className="bg-primary text-primary-foreground absolute top-1 right-1 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[0.62rem] font-semibold" aria-hidden>
              {unread > 9 ? '9+' : unread}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        <header className="flex items-center justify-between border-b px-4 py-2.5">
          <h2 className="text-sm font-semibold">Notifications</h2>
          {unread > 0 ? (
            <button type="button" onClick={() => markRead.mutate(undefined)} className="text-primary text-xs font-medium hover:underline">
              Mark all as read
            </button>
          ) : null}
        </header>
        {!data?.items.length ? (
          <p className="text-muted-foreground px-4 py-8 text-center text-sm">
            Nothing yet. You&apos;ll hear here when documents finish processing or someone invites you.
          </p>
        ) : (
          <ul className="max-h-96 divide-y overflow-y-auto">
            {data.items.map((n) => (
              <NotificationRow key={n.id} n={n} onDone={() => setOpen(false)} />
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}

function NotificationRow({ n, onDone }: { n: Notification; onDone: () => void }) {
  const navigate = useNavigate()
  const markRead = useMarkRead()
  const accept = useAcceptInvitationById()
  const { icon: Icon, className } = icons[n.type]

  const open = () => {
    if (!n.read) markRead.mutate([n.id])
    if (n.link) {
      onDone()
      navigate(n.link)
    }
  }

  return (
    <li className={cn('flex gap-3 px-4 py-3', !n.read && 'bg-accent/40')}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', className)} aria-hidden />
      <div className="min-w-0 flex-1">
        <button type="button" onClick={open} className="block w-full text-left">
          <span className="block text-sm font-medium">{n.title}</span>
          {n.body ? <span className="text-muted-foreground line-clamp-2 block text-xs">{n.body}</span> : null}
          <span className="text-muted-foreground mt-1 block text-[0.7rem]">
            {timeAgo(n.created_at)}
            {!n.read ? <span className="sr-only"> (unread)</span> : null}
          </span>
        </button>
        {n.type === 'invitation' && n.invitation_id && !n.read ? (
          <Button
            size="xs"
            className="mt-2"
            disabled={accept.isPending}
            onClick={() =>
              accept.mutate(n.invitation_id as string, {
                onSuccess: (ws) => {
                  markRead.mutate([n.id])
                  toast.success(`You joined ${ws.name}`)
                  onDone()
                  navigate(`/w/${ws.id}`)
                },
                onError: (e) => {
                  markRead.mutate([n.id])
                  toast.error(toApiError(e).code === 'invalid_invitation' ? 'This invitation is no longer valid.' : toApiError(e).message)
                },
              })
            }
          >
            {accept.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null} Join workspace
          </Button>
        ) : null}
      </div>
      {!n.read ? <span className="bg-primary mt-1.5 size-2 shrink-0 rounded-full" aria-hidden /> : null}
    </li>
  )
}
