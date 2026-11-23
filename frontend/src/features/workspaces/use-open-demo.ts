import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useDemoStatus, useJoinDemo } from '@/features/workspaces/api'
import { toApiError } from '@/lib/api'

/** Opens the shared demo workspace (joining it first if needed). Navigates on success. */
export function useOpenDemo() {
  const { data } = useDemoStatus()
  const join = useJoinDemo()
  const navigate = useNavigate()
  const open = () => {
    if (data?.joined && data.workspace_id) {
      navigate(`/w/${data.workspace_id}`)
      return
    }
    join.mutate(undefined, {
      onSuccess: ({ workspace_id }) => navigate(`/w/${workspace_id}`),
      onError: (e) => toast.error(toApiError(e).message),
    })
  }
  return { available: !!data?.available, joined: !!data?.joined, open, pending: join.isPending }
}
