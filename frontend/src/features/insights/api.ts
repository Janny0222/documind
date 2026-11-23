import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { http } from '@/lib/api'
import type { FileType, Scope } from '@/lib/types'

// ---------------------------------------------------------------- types (mirror backend/app/schemas/insights.py)

export interface SearchHit {
  chunk_id: string
  document_id: string
  document_title: string
  file_type: FileType
  page_number: number | null
  page_unit: 'page' | 'section'
  char_start: number
  char_end: number
  text: string
  score: number
  similarity: number | null
  keyword_match: boolean
}

export interface SearchResponse {
  query: string
  mode: 'hybrid' | 'keyword'
  hits: SearchHit[]
}

export interface Analytics {
  days: number
  since: string
  totals: {
    questions: number
    answered: number
    not_found: number
    failed: number
    rate_limited: number
    input_tokens: number
    output_tokens: number
    est_cost_usd: number
  }
  daily: { date: string; questions: number; input_tokens: number; output_tokens: number }[]
  by_operation: { operation: string; calls: number; input_tokens: number; output_tokens: number; errors: number }[]
  documents: {
    total: number
    ready: number
    processing: number
    failed: number
    storage_bytes: number
    by_type: Record<FileType, number>
    uploads_in_range: number
  }
  top_members: { user_id: string | null; display_name: string; questions: number }[]
  recent_errors: { created_at: string; operation: string; status: string; model: string }[]
  limits: Record<string, number>
}

export interface ActivityItem {
  id: string
  action: string
  actor: string | null
  target_type: string | null
  target_id: string | null
  meta: Record<string, unknown>
  created_at: string
}

export interface Notification {
  id: string
  type: 'document_ready' | 'document_failed' | 'invitation' | 'member_joined'
  title: string
  body: string
  link: string | null
  invitation_id: string | null
  workspace_id: string | null
  read: boolean
  created_at: string
}

// ---------------------------------------------------------------- hooks

export function useSearch(ws: string, query: string, scope: Scope) {
  return useQuery({
    queryKey: ['workspaces', ws, 'search', query, scope],
    queryFn: () => http.post<SearchResponse>(`/workspaces/${ws}/search`, { query, scope, limit: 15 }),
    enabled: query.trim().length >= 2,
    staleTime: 60_000,
  })
}

export const useAnalytics = (ws: string, days: number, enabled: boolean) =>
  useQuery({
    queryKey: ['workspaces', ws, 'analytics', days],
    queryFn: () => http.get<Analytics>(`/workspaces/${ws}/analytics`, { params: { days } }),
    enabled,
  })

export const useActivity = (ws: string, enabled: boolean) =>
  useInfiniteQuery({
    queryKey: ['workspaces', ws, 'activity'],
    queryFn: ({ pageParam }) =>
      http.get<{ items: ActivityItem[]; next_before: string | null }>(`/workspaces/${ws}/activity`, {
        params: { limit: 30, ...(pageParam ? { before: pageParam } : {}) },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before,
    enabled,
  })

export const notificationKeys = { all: ['notifications'] as const }

/** Polled every 30s - cheap, and no WebSocket infrastructure needed on free hosting. */
export const useNotifications = () =>
  useQuery({
    queryKey: notificationKeys.all,
    queryFn: () => http.get<{ items: Notification[]; unread: number }>('/notifications', { params: { limit: 20 } }),
    refetchInterval: 30_000,
  })

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids?: string[]) => http.post<{ updated: number }>('/notifications/read', ids ? { ids } : {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationKeys.all }),
  })
}

export function useAcceptInvitationById() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (invitationId: string) => http.post<{ id: string; name: string }>(`/invitations/${invitationId}/accept`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['workspaces'] })
      void qc.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}
