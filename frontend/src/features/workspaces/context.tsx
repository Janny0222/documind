import { type ReactNode, useEffect } from 'react'
import { Navigate, useParams } from 'react-router'
import { FullPageLoader } from '@/features/auth/guards'
import { useWorkspaces } from '@/features/workspaces/api'
import { WorkspaceContext } from '@/features/workspaces/current'
import { usePreferences } from '@/stores/preferences'

/** Picks the workspace to open at "/": the last one used, else the personal workspace. */
export function WorkspaceHome() {
  const { data: workspaces, isPending } = useWorkspaces()
  const lastId = usePreferences((s) => s.lastWorkspaceId)
  if (isPending || !workspaces) return <FullPageLoader />
  const target =
    workspaces.find((w) => w.id === lastId) ?? workspaces.find((w) => w.is_personal) ?? workspaces[0]
  if (!target) return <FullPageLoader label="Setting up your workspace" />
  return <Navigate to={`/w/${target.id}`} replace />
}

/**
 * Resolves :workspaceId against the user's memberships. The URL is only a hint: an id that
 * isn't in *your* list (removed, deleted, or someone else's) sends you home. The API enforces
 * the same rule server-side with a 404.
 */
export function WorkspaceGate({ children }: { children: ReactNode }) {
  const { workspaceId } = useParams()
  const { data: workspaces, isPending } = useWorkspaces()
  const setLast = usePreferences((s) => s.setLastWorkspaceId)
  const workspace = workspaces?.find((w) => w.id === workspaceId) ?? null

  useEffect(() => {
    if (workspace) setLast(workspace.id)
  }, [workspace, setLast])

  if (isPending) return <FullPageLoader />
  if (!workspace) return <Navigate to="/" replace />
  return <WorkspaceContext value={workspace}>{children}</WorkspaceContext>
}
