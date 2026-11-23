import { Check, Copy, Link2, Loader2, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { EmptyState } from '@/components/EmptyState'
import { Field } from '@/components/forms/Field'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useMe } from '@/features/auth/api'
import { SettingsSection } from '@/features/settings/SettingsLayout'
import {
  useCreateInvitation,
  useInvitations,
  useMembers,
  useRemoveMember,
  useRevokeInvitation,
  useUpdateMemberRole,
} from '@/features/workspaces/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { initials } from '@/lib/format'
import { toApiError } from '@/lib/api'
import { type AssignableRole, atLeast, type Member, type Role } from '@/lib/types'

const roleLabel: Record<Role, string> = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' }
const roleHelp: Record<AssignableRole, string> = {
  admin: 'Manage members and settings',
  member: 'Upload, organize and ask',
  viewer: 'Read and ask only',
}

/** Mirrors the server rules so the UI only offers what will succeed (the API still decides). */
function manageableRoles(actor: Role): AssignableRole[] {
  return actor === 'owner' ? ['admin', 'member', 'viewer'] : actor === 'admin' ? ['member', 'viewer'] : []
}

function canManage(actor: Role, target: Role) {
  if (target === 'owner') return false
  if (actor === 'owner') return true
  return actor === 'admin' && (target === 'member' || target === 'viewer')
}

const selectClass =
  'border-input bg-card h-9 rounded-md border px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60'

export function MembersSettings() {
  const workspace = useCurrentWorkspace()
  const isAdmin = atLeast(workspace.role, 'admin')
  return (
    <div className="grid gap-6">
      {workspace.is_personal ? (
        <SettingsSection title="Members">
          <p className="text-muted-foreground text-sm">
            Personal workspaces are private to you. Create a team workspace from the workspace
            menu to work with others.
          </p>
        </SettingsSection>
      ) : (
        <>
          {isAdmin ? <InviteSection /> : null}
          <MemberList />
          {isAdmin ? <PendingInvitations /> : null}
        </>
      )}
    </div>
  )
}

function InviteSection() {
  const workspace = useCurrentWorkspace()
  const create = useCreateInvitation(workspace.id)
  const roles = manageableRoles(workspace.role)
  const [role, setRole] = useState<AssignableRole>('member')
  const [email, setEmail] = useState('')
  const [link, setLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    create.mutate(
      { role, ...(email.trim() ? { email: email.trim() } : {}) },
      {
        onSuccess: (inv) => {
          setLink(inv.invite_url)
          setCopied(false)
          setEmail('')
        },
        onError: (err) => toast.error(toApiError(err).message),
      },
    )
  }

  return (
    <SettingsSection
      title="Invite people"
      description="Create a single-use invite link. Add an email to make sure only that person can use it."
    >
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-end">
        <Field
          label="Email (optional)"
          type="email"
          placeholder="name@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="grid gap-1.5">
          <Label htmlFor="invite-role">Role</Label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as AssignableRole)}
            className={`${selectClass} h-10`}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {roleLabel[r]} - {roleHelp[r]}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" className="h-10" disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Link2 aria-hidden />}
          Create link
        </Button>
      </form>
      {link ? (
        <div className="bg-muted mt-5 rounded-lg p-3" role="status">
          <p className="text-muted-foreground mb-2 text-[0.8rem]">
            Copy this link now - for security it&apos;s only shown once. It expires in 7 days.
          </p>
          <div className="flex items-center gap-2">
            <code className="bg-card min-w-0 flex-1 truncate rounded-md border px-2.5 py-2 text-[0.8rem]">{link}</code>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await navigator.clipboard.writeText(link)
                setCopied(true)
                toast.success('Invite link copied')
              }}
            >
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
        </div>
      ) : null}
    </SettingsSection>
  )
}

function MemberList() {
  const workspace = useCurrentWorkspace()
  const { data: members, isPending } = useMembers(workspace.id)
  return (
    <SettingsSection title="Members" description={`${workspace.member_count} ${workspace.member_count === 1 ? 'person has' : 'people have'} access.`}>
      <ul className="divide-y">
        {isPending
          ? [0, 1, 2].map((i) => (
              <li key={i} className="flex items-center gap-3 py-3">
                <Skeleton className="size-9 rounded-full" />
                <Skeleton className="h-4 w-48" />
              </li>
            ))
          : members?.map((m) => <MemberRow key={m.user_id} member={m} />)}
      </ul>
    </SettingsSection>
  )
}

function MemberRow({ member }: { member: Member }) {
  const workspace = useCurrentWorkspace()
  const { data: me } = useMe()
  const update = useUpdateMemberRole(workspace.id)
  const remove = useRemoveMember(workspace.id)
  const isSelf = me?.id === member.user_id
  const editable = !isSelf && canManage(workspace.role, member.role)
  const options = manageableRoles(workspace.role)

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <Avatar className="size-9">
        <AvatarFallback className="bg-accent text-accent-foreground text-xs font-semibold">
          {initials(member.display_name)}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {member.display_name}
          {isSelf ? <span className="text-muted-foreground font-normal"> (you)</span> : null}
        </p>
        <p className="text-muted-foreground truncate text-xs">{member.email}</p>
      </div>
      {editable ? (
        <>
          <label className="sr-only" htmlFor={`role-${member.user_id}`}>
            Role for {member.display_name}
          </label>
          <select
            id={`role-${member.user_id}`}
            value={member.role}
            disabled={update.isPending}
            onChange={(e) =>
              update.mutate(
                { userId: member.user_id, role: e.target.value as AssignableRole },
                {
                  onSuccess: (m) => toast.success(`${m.display_name} is now ${roleLabel[m.role].toLowerCase()}`),
                  onError: (err) => toast.error(toApiError(err).message),
                },
              )
            }
            className={selectClass}
          >
            {/* Keep the current role selectable even if this actor couldn't assign it. */}
            {[...new Set([member.role as AssignableRole, ...options])].map((r) => (
              <option key={r} value={r}>
                {roleLabel[r]}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove ${member.display_name}`}
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(member.user_id, {
                onSuccess: () => toast.success(`Removed ${member.display_name}`),
                onError: (err) => toast.error(toApiError(err).message),
              })
            }
          >
            <Trash2 aria-hidden />
          </Button>
        </>
      ) : (
        <span className="text-muted-foreground text-sm">{roleLabel[member.role]}</span>
      )}
    </li>
  )
}

function PendingInvitations() {
  const workspace = useCurrentWorkspace()
  const { data: invitations, isPending } = useInvitations(workspace.id, true)
  const revoke = useRevokeInvitation(workspace.id)
  return (
    <SettingsSection title="Pending invitations">
      {isPending ? (
        <Skeleton className="h-10 w-full" />
      ) : !invitations?.length ? (
        <EmptyState icon={Link2} title="No pending invitations" className="py-6" />
      ) : (
        <ul className="divide-y">
          {invitations.map((inv) => (
            <li key={inv.id} className="flex items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{inv.email ?? 'Anyone with the link'}</p>
                <p className="text-muted-foreground text-xs">
                  {roleLabel[inv.role]}, expires {new Date(inv.expires_at).toLocaleDateString()}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={revoke.isPending}
                onClick={() =>
                  revoke.mutate(inv.id, {
                    onSuccess: () => toast.success('Invitation revoked'),
                    onError: (err) => toast.error(toApiError(err).message),
                  })
                }
              >
                <X aria-hidden /> Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  )
}
