import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { http } from '@/lib/api'
import { queryKeys } from '@/lib/query-client'
import {
  type Collection,
  type DocumentItem,
  type DocumentList,
  type DocumentPage,
  type DocumentSort,
  type FileType,
  isProcessing,
} from '@/lib/types'

const base = (ws: string) => `/workspaces/${ws}`

export interface DocumentFilters {
  q?: string
  type?: FileType
  collection_id?: string
  sort?: DocumentSort
}

/** Polls every 3s while any listed document is still processing, then stops. */
export function useDocuments(ws: string, filters: DocumentFilters = {}) {
  const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
  return useQuery({
    queryKey: queryKeys.documentList(ws, params),
    queryFn: () => http.get<DocumentList>(`${base(ws)}/documents`, { params: { limit: 100, ...params } }),
    placeholderData: keepPreviousData, // keep the grid steady while filters change
    refetchInterval: (query) => (query.state.data?.items.some((d) => isProcessing(d.status)) ? 3000 : false),
  })
}

export const useDocument = (ws: string, id: string | null) =>
  useQuery({
    queryKey: queryKeys.document(ws, id ?? ''),
    queryFn: () => http.get<DocumentItem>(`${base(ws)}/documents/${id}`),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data && isProcessing(query.state.data.status) ? 3000 : false),
  })

export const useDocumentPage = (ws: string, id: string, page: number, enabled: boolean) =>
  useQuery({
    queryKey: queryKeys.documentPage(ws, id, page),
    queryFn: () => http.get<DocumentPage>(`${base(ws)}/documents/${id}/pages/${page}`),
    enabled,
    staleTime: Infinity, // page text never changes once indexed
    placeholderData: keepPreviousData,
  })

function useInvalidateDocuments(ws: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.documents(ws) })
    void qc.invalidateQueries({ queryKey: queryKeys.collections(ws) })
  }
}

export function useRenameDocument(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      http.patch<DocumentItem>(`${base(ws)}/documents/${id}`, { title }),
    onSuccess: invalidate,
  })
}

export function useDeleteDocument(ws: string) {
  const qc = useQueryClient()
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: (id: string) => http.delete<void>(`${base(ws)}/documents/${id}`),
    // Optimistic: the card disappears immediately; it comes back if the server refuses.
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: queryKeys.documents(ws) })
      const snapshots = qc.getQueriesData<DocumentList>({ queryKey: [...queryKeys.documents(ws), 'list'] })
      for (const [key, data] of snapshots) {
        if (data) qc.setQueryData<DocumentList>(key, { ...data, items: data.items.filter((d) => d.id !== id), total: data.total - 1 })
      }
      return { snapshots }
    },
    onError: (_err, _id, context) => {
      for (const [key, data] of context?.snapshots ?? []) qc.setQueryData(key, data)
    },
    onSettled: invalidate,
  })
}

export function useReprocessDocument(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: (id: string) => http.post<DocumentItem>(`${base(ws)}/documents/${id}/reprocess`),
    onSuccess: invalidate,
  })
}

export async function downloadDocument(ws: string, id: string) {
  const { url } = await http.get<{ url: string }>(`${base(ws)}/documents/${id}/download`)
  // Same-origin API URL (local) or a 60-second presigned R2 URL (production).
  window.location.assign(url)
}

// ---------------------------------------------------------------- collections

export const useCollections = (ws: string) =>
  useQuery({ queryKey: queryKeys.collections(ws), queryFn: () => http.get<Collection[]>(`${base(ws)}/collections`) })

export function useCreateCollection(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) => http.post<Collection>(`${base(ws)}/collections`, body),
    onSuccess: invalidate,
  })
}

export function useUpdateCollection(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string }) =>
      http.patch<Collection>(`${base(ws)}/collections/${id}`, body),
    onSuccess: invalidate,
  })
}

export function useDeleteCollection(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: (id: string) => http.delete<void>(`${base(ws)}/collections/${id}`),
    onSuccess: invalidate,
  })
}

export function useSetCollectionMembership(ws: string) {
  const invalidate = useInvalidateDocuments(ws)
  return useMutation({
    mutationFn: ({ collectionId, documentIds, add }: { collectionId: string; documentIds: string[]; add: boolean }) =>
      add
        ? http.put<Collection>(`${base(ws)}/collections/${collectionId}/documents`, { document_ids: documentIds })
        : http.delete<Collection>(`${base(ws)}/collections/${collectionId}/documents`, { document_ids: documentIds }),
    onSuccess: invalidate,
  })
}
