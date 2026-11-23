import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'
import { Field, FormAlert } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useCreateWorkspace } from '@/features/workspaces/api'
import { applyServerErrors } from '@/lib/form-errors'

const schema = z.object({ name: z.string().trim().min(1, 'Give the workspace a name').max(80) })
type Values = z.infer<typeof schema>

export function CreateWorkspaceDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const create = useCreateWorkspace()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState, reset } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: '' },
  })

  const onSubmit = handleSubmit(async ({ name }) => {
    setFormError(null)
    try {
      const ws = await create.mutateAsync(name)
      toast.success(`Created ${ws.name}`)
      onOpenChange(false)
      reset()
      navigate(`/w/${ws.id}`)
    } catch (err) {
      setFormError(
        applyServerErrors(err, setError, ['name'], {
          workspace_limit: 'You own the maximum number of workspaces. Delete one to create another.',
        }),
      )
    }
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o) {
          reset()
          setFormError(null)
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={onSubmit} noValidate className="grid gap-5">
          <DialogHeader>
            <DialogTitle>Create a workspace</DialogTitle>
            <DialogDescription>
              A separate space with its own documents, members and conversations. Nothing is
              shared between workspaces.
            </DialogDescription>
          </DialogHeader>
          {formError ? <FormAlert>{formError}</FormAlert> : null}
          <Field
            label="Workspace name"
            placeholder="e.g. Marketing team"
            autoFocus
            error={formState.errors.name?.message}
            {...register('name')}
          />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={formState.isSubmitting}>
              {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Create workspace
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
