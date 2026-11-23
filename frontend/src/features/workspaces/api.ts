import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { http } from '@/lib/api'
import { queryKeys } from '@/lib/query-client'
import type {
  AssignableRole,
  Invitation,
  InvitationCreated,
  InvitationPreview,
  Member,
  Workspace,
} from '@/lib/types'

const base = (id: string) => `/workspaces/${id}`

export const useWorkspaces = () =>
  useQuery({
    queryKey: queryKeys.workspaces,
    queryFn: () => http.get<Workspace[]>('/workspaces'),
  })

export function useCreateWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => http.post<Workspace>('/workspaces', { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export function useRenameWorkspace(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => http.patch<Workspace>(base(id), { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export function useDeleteWorkspace(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (confirmName: string) => http.delete<void>(base(id), { confirm_name: confirmName }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export function useGrantAiConsent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => http.post<Workspace>(`${base(id)}/ai-consent`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export const useMembers = (id: string) =>
  useQuery({ queryKey: queryKeys.members(id), queryFn: () => http.get<Member[]>(`${base(id)}/members`) })

export function useUpdateMemberRole(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: AssignableRole }) =>
      http.patch<Member>(`${base(id)}/members/${userId}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.members(id) }),
  })
}

export function useRemoveMember(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => http.delete<void>(`${base(id)}/members/${userId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.members(id) })
      void qc.invalidateQueries({ queryKey: queryKeys.workspaces })
    },
  })
}

export const useInvitations = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: queryKeys.invitations(id),
    queryFn: () => http.get<Invitation[]>(`${base(id)}/invitations`),
    enabled,
  })

export function useCreateInvitation(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { role: AssignableRole; email?: string }) =>
      http.post<InvitationCreated>(`${base(id)}/invitations`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.invitations(id) }),
  })
}

export function useRevokeInvitation(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (invitationId: string) => http.delete<void>(`${base(id)}/invitations/${invitationId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.invitations(id) }),
  })
}

export const usePreviewInvitation = (token: string | null) =>
  useQuery({
    queryKey: ['invitation-preview', token],
    queryFn: () => http.post<InvitationPreview>('/invitations/preview', { token }),
    enabled: !!token,
    retry: false,
  })

export function useAcceptInvitation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => http.post<Workspace>('/invitations/accept', { token }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

// ------------------------------------------------------------------ shared demo workspace

export interface DemoStatus {
  available: boolean
  joined: boolean
  workspace_id: string | null
}

export const useDemoStatus = () =>
  useQuery({ queryKey: ['demo'], queryFn: () => http.get<DemoStatus>('/demo'), staleTime: 5 * 60_000 })

export function useJoinDemo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => http.post<{ workspace_id: string }>('/demo/join'),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: queryKeys.workspaces })
      await qc.invalidateQueries({ queryKey: ['demo'] })
    },
  })
}
