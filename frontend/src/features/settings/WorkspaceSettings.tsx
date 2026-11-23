import { zodResolver } from '@hookform/resolvers/zod'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'
import { Field } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useMe } from '@/features/auth/api'
import { SettingsSection } from '@/features/settings/SettingsLayout'
import { useDeleteWorkspace, useGrantAiConsent, useRemoveMember, useRenameWorkspace } from '@/features/workspaces/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { toApiError } from '@/lib/api'
import { atLeast } from '@/lib/types'

const nameSchema = z.object({ name: z.string().trim().min(1, 'Give the workspace a name').max(80) })

export function WorkspaceSettings() {
  const workspace = useCurrentWorkspace()
  const isAdmin = atLeast(workspace.role, 'admin')
  return (
    <div className="grid gap-6">
      <GeneralSection key={workspace.id} canEdit={isAdmin} />
      <AiSection canEdit={isAdmin} />
      {workspace.role === 'owner' && !workspace.is_personal ? <DeleteSection /> : null}
      {workspace.role !== 'owner' ? <LeaveSection /> : null}
    </div>
  )
}

function GeneralSection({ canEdit }: { canEdit: boolean }) {
  const workspace = useCurrentWorkspace()
  const rename = useRenameWorkspace(workspace.id)
  const { register, handleSubmit, formState, reset } = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: workspace.name },
  })
  const onSubmit = handleSubmit(async ({ name }) => {
    try {
      const ws = await rename.mutateAsync(name)
      reset({ name: ws.name })
      toast.success('Workspace renamed')
    } catch (e) {
      toast.error(toApiError(e).message)
    }
  })
  return (
    <SettingsSection
      title="General"
      description={canEdit ? 'Everyone in the workspace sees this name.' : 'Only admins can rename the workspace.'}
    >
      <form onSubmit={onSubmit} noValidate className="grid max-w-md gap-5">
        <Field label="Workspace name" disabled={!canEdit} error={formState.errors.name?.message} {...register('name')} />
        {canEdit ? (
          <div>
            <Button type="submit" disabled={!formState.isDirty || formState.isSubmitting}>
              {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Save name
            </Button>
          </div>
        ) : null}
      </form>
    </SettingsSection>
  )
}

function AiSection({ canEdit }: { canEdit: boolean }) {
  const workspace = useCurrentWorkspace()
  const grant = useGrantAiConsent(workspace.id)
  return (
    <SettingsSection
      title="AI processing"
      description="To answer questions, DocuMind sends the relevant passages of your documents to Google Gemini. On the free tier Google may use that content to improve its products, and it can be reviewed by people. Don't index confidential documents."
    >
      {workspace.ai_consent ? (
        <p className="text-success flex items-center gap-2 text-sm font-medium">
          <CheckCircle2 className="size-4" aria-hidden /> Allowed for this workspace
        </p>
      ) : canEdit ? (
        <Button
          variant="outline"
          disabled={grant.isPending}
          onClick={() =>
            grant.mutate(undefined, {
              onSuccess: () => toast.success('AI processing allowed'),
              onError: (e) => toast.error(toApiError(e).message),
            })
          }
        >
          {grant.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
          I understand - allow AI processing
        </Button>
      ) : (
        <p className="text-muted-foreground text-sm">Not allowed yet. Ask a workspace admin to turn it on.</p>
      )}
    </SettingsSection>
  )
}

function DeleteSection() {
  const workspace = useCurrentWorkspace()
  const del = useDeleteWorkspace(workspace.id)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  return (
    <SettingsSection
      tone="danger"
      title="Delete workspace"
      description="Permanently deletes the workspace with all its documents, conversations and members. This can't be undone."
    >
      <Button variant="destructive" onClick={() => setOpen(true)}>
        Delete workspace
      </Button>
      <Dialog open={open} onOpenChange={(o) => (setOpen(o), setTyped(''))}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {workspace.name}?</DialogTitle>
            <DialogDescription>
              Everything in this workspace is removed for every member. Type the workspace name to
              confirm.
            </DialogDescription>
          </DialogHeader>
          <Field label="Workspace name" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={typed !== workspace.name || del.isPending}
              onClick={() =>
                del.mutate(typed, {
                  onSuccess: () => {
                    toast.success(`Deleted ${workspace.name}`)
                    navigate('/', { replace: true })
                  },
                  onError: (e) => toast.error(toApiError(e).message),
                })
              }
            >
              {del.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  )
}

function LeaveSection() {
  const workspace = useCurrentWorkspace()
  const { data: me } = useMe()
  const remove = useRemoveMember(workspace.id)
  const navigate = useNavigate()
  return (
    <SettingsSection tone="danger" title="Leave workspace" description="You'll lose access until someone invites you again.">
      <Button
        variant="destructive"
        disabled={!me || remove.isPending}
        onClick={() =>
          me &&
          remove.mutate(me.id, {
            onSuccess: () => {
              toast.success(`You left ${workspace.name}`)
              navigate('/', { replace: true })
            },
            onError: (e) => toast.error(toApiError(e).message),
          })
        }
      >
        Leave {workspace.name}
      </Button>
    </SettingsSection>
  )
}
