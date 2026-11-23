import { Loader2, MailX, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useMe } from '@/features/auth/api'
import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { FullPageLoader } from '@/features/auth/guards'
import { useAcceptInvitation, usePreviewInvitation } from '@/features/workspaces/api'
import { toApiError } from '@/lib/api'
import { takeHashToken } from '@/lib/form-errors'

const STASH = 'documind-invite-token'

/** The token arrives in the URL fragment. Keep it for this tab only while the user signs in. */
function useInviteToken(): string | null {
  const [token] = useState(() => {
    const fromHash = takeHashToken()
    if (fromHash) sessionStorage.setItem(STASH, fromHash)
    return fromHash ?? sessionStorage.getItem(STASH)
  })
  return token
}

const roleText = { owner: 'an owner', admin: 'an admin', member: 'a member', viewer: 'a viewer' } as const

export function InvitePage() {
  const token = useInviteToken()
  const { data: user, isPending: mePending } = useMe()
  const preview = usePreviewInvitation(user ? token : null)
  const accept = useAcceptInvitation()
  const navigate = useNavigate()

  if (mePending) return <FullPageLoader />
  if (!user) return <Navigate to="/login?next=%2Finvite" replace />

  if (!token || preview.isError) {
    return (
      <AuthLayout
        title="This invitation can't be used"
        footer={<Link to="/" className="text-primary font-medium hover:underline">Go to your workspaces</Link>}
      >
        <div className="flex gap-3">
          <MailX className="text-destructive mt-0.5 size-5 shrink-0" aria-hidden />
          <p className="text-muted-foreground">
            It may have expired, been revoked or already used - or it was sent to a different
            email than <span className="text-foreground font-medium">{user.email}</span>. Ask the
            person who invited you for a new link.
          </p>
        </div>
      </AuthLayout>
    )
  }

  if (preview.isPending) return <FullPageLoader label="Checking invitation" />
  const inv = preview.data

  return (
    <AuthLayout title={`Join ${inv.workspace_name}`} subtitle={`${inv.invited_by ?? 'Someone'} invited you as ${roleText[inv.role]}.`}>
      <div className="bg-muted flex items-center gap-3 rounded-lg p-3 text-sm">
        <Users className="text-primary size-4 shrink-0" aria-hidden />
        You&apos;ll join as <span className="font-medium">{user.email}</span>
      </div>
      <div className="mt-6 grid gap-3">
        <Button
          size="lg"
          disabled={accept.isPending}
          onClick={() =>
            accept.mutate(token, {
              onSuccess: (ws) => {
                sessionStorage.removeItem(STASH)
                toast.success(`You joined ${ws.name}`)
                navigate(`/w/${ws.id}`, { replace: true })
              },
              onError: (e) => {
                const err = toApiError(e)
                if (err.code === 'already_member') {
                  sessionStorage.removeItem(STASH)
                  navigate(`/w/${inv.workspace_id}`, { replace: true })
                } else toast.error(err.message)
              },
            })
          }
        >
          {accept.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Join workspace
        </Button>
        <Button variant="ghost" asChild>
          <Link to="/" onClick={() => sessionStorage.removeItem(STASH)}>
            Not now
          </Link>
        </Button>
      </div>
    </AuthLayout>
  )
}
