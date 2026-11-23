import { createContext, use } from 'react'
import type { Workspace } from '@/lib/types'

export const WorkspaceContext = createContext<Workspace | null>(null)

/** The workspace for the current /w/:workspaceId route. Only valid inside <WorkspaceGate>. */
export function useCurrentWorkspace(): Workspace {
  const ws = use(WorkspaceContext)
  if (!ws) throw new Error('useCurrentWorkspace must be used inside <WorkspaceGate>')
  return ws
}
