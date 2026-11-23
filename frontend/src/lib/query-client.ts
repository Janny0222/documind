import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/lib/api'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          // Client errors are final; only retry network/5xx hiccups, twice.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          return failureCount < 2
        },
      },
      mutations: { retry: false },
    },
  })
}

export const queryKeys = {
  me: ['me'] as const,
  workspaces: ['workspaces'] as const,
  workspace: (id: string) => ['workspaces', id] as const,
  members: (id: string) => ['workspaces', id, 'members'] as const,
  invitations: (id: string) => ['workspaces', id, 'invitations'] as const,
  documents: (ws: string) => ['workspaces', ws, 'documents'] as const,
  documentList: (ws: string, params: object) => ['workspaces', ws, 'documents', 'list', params] as const,
  document: (ws: string, id: string) => ['workspaces', ws, 'documents', 'item', id] as const,
  documentPage: (ws: string, id: string, page: number) => ['workspaces', ws, 'documents', 'page', id, page] as const,
  collections: (ws: string) => ['workspaces', ws, 'collections'] as const,
}
