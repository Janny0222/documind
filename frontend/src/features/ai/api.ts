import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { http } from '@/lib/api'
import type { AiStatus, Conversation, ConversationDetail, Scope } from '@/lib/types'

const base = (ws: string) => `/workspaces/${ws}`

export const aiKeys = {
  status: (ws: string) => ['workspaces', ws, 'ai', 'status'] as const,
  conversations: (ws: string) => ['workspaces', ws, 'conversations'] as const,
  conversation: (ws: string, id: string) => ['workspaces', ws, 'conversations', id] as const,
}

export const useAiStatus = (ws: string) =>
  useQuery({ queryKey: aiKeys.status(ws), queryFn: () => http.get<AiStatus>(`${base(ws)}/ai/status`) })

export const useConversations = (ws: string) =>
  useQuery({ queryKey: aiKeys.conversations(ws), queryFn: () => http.get<Conversation[]>(`${base(ws)}/conversations`) })

export const useConversation = (ws: string, id: string | undefined) =>
  useQuery({
    queryKey: aiKeys.conversation(ws, id ?? ''),
    queryFn: () => http.get<ConversationDetail>(`${base(ws)}/conversations/${id}`),
    enabled: !!id,
  })

export function useCreateConversation(ws: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { scope: Scope; title?: string }) => http.post<Conversation>(`${base(ws)}/conversations`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiKeys.conversations(ws) }),
  })
}

export function useUpdateConversation(ws: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; title?: string; scope?: Scope }) =>
      http.patch<Conversation>(`${base(ws)}/conversations/${id}`, body),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: aiKeys.conversations(ws) })
      void qc.invalidateQueries({ queryKey: aiKeys.conversation(ws, c.id) })
    },
  })
}

export function useDeleteConversation(ws: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => http.delete<void>(`${base(ws)}/conversations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiKeys.conversations(ws) }),
  })
}

export const askPath = (ws: string, conversationId: string) => `${base(ws)}/conversations/${conversationId}/messages`
export const regeneratePath = (ws: string, conversationId: string, messageId: string) =>
  `${base(ws)}/conversations/${conversationId}/messages/${messageId}/regenerate`
