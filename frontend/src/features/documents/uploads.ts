/**
 * Client-side upload queue. One request per file (so each gets its own progress bar and its
 * own error), two at a time. Lives in Zustand so uploads keep going while you navigate.
 */
import type { QueryClient } from '@tanstack/react-query'
import { create } from 'zustand'
import { api, toApiError } from '@/lib/api'
import { queryKeys } from '@/lib/query-client'
import type { UploadResult } from '@/lib/types'

export const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.txt']
export const ACCEPT_ATTR = '.pdf,.docx,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
export const MAX_FILE_MB = 10
const CONCURRENCY = 2

export type UploadState = 'waiting' | 'uploading' | 'done' | 'duplicate' | 'rejected' | 'error'

export interface UploadItem {
  id: string
  workspaceId: string
  name: string
  size: number
  progress: number // 0..1
  state: UploadState
  message: string | null
  documentId: string | null
}

interface UploadStore {
  items: UploadItem[]
  update: (id: string, patch: Partial<UploadItem>) => void
  add: (items: UploadItem[]) => void
  clearFinished: () => void
}

export const useUploads = create<UploadStore>()((set) => ({
  items: [],
  update: (id, patch) => set((s) => ({ items: s.items.map((i) => (i.id === id ? { ...i, ...patch } : i)) })),
  add: (items) => set((s) => ({ items: [...s.items, ...items] })),
  clearFinished: () =>
    set((s) => ({ items: s.items.filter((i) => i.state === 'waiting' || i.state === 'uploading') })),
}))

/** Quick checks before spending bandwidth. The server re-validates everything by content. */
export function precheck(file: File): string | null {
  const name = file.name.toLowerCase()
  if (name.endsWith('.doc')) return 'Old .doc files aren’t supported. Save it as .docx or PDF.'
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) return 'Only PDF, DOCX and TXT files are supported.'
  if (file.size === 0) return 'This file is empty.'
  if (file.size > MAX_FILE_MB * 1024 * 1024) return `Files can be at most ${MAX_FILE_MB} MB.`
  return null
}

const queue: { item: UploadItem; file: File; qc: QueryClient }[] = []
let active = 0

export function enqueueUploads(workspaceId: string, files: File[], qc: QueryClient) {
  const { add } = useUploads.getState()
  const items: UploadItem[] = files.map((file) => {
    const problem = precheck(file)
    return {
      id: crypto.randomUUID(),
      workspaceId,
      name: file.name,
      size: file.size,
      progress: 0,
      state: problem ? 'rejected' : 'waiting',
      message: problem,
      documentId: null,
    }
  })
  add(items)
  items.forEach((item, i) => {
    const file = files[i]
    if (item.state === 'waiting' && file) queue.push({ item, file, qc })
  })
  pump()
}

function pump() {
  while (active < CONCURRENCY && queue.length > 0) {
    const next = queue.shift()
    if (!next) break
    active += 1
    void runOne(next.item, next.file, next.qc).finally(() => {
      active -= 1
      pump()
    })
  }
}

async function runOne(item: UploadItem, file: File, qc: QueryClient) {
  const { update } = useUploads.getState()
  update(item.id, { state: 'uploading' })
  const form = new FormData()
  form.append('files', file)
  try {
    const { data } = await api.post<UploadResult[]>(`/workspaces/${item.workspaceId}/documents`, form, {
      onUploadProgress: (e) => update(item.id, { progress: e.total ? e.loaded / e.total : 0 }),
    })
    const result = data[0]
    if (!result || result.outcome === 'rejected') {
      update(item.id, { state: 'rejected', message: result?.detail ?? 'The file was rejected.' })
    } else if (result.outcome === 'duplicate') {
      update(item.id, { state: 'duplicate', progress: 1, message: 'Already in this workspace', documentId: result.document?.id ?? null })
    } else {
      update(item.id, { state: 'done', progress: 1, documentId: result.document?.id ?? null })
    }
  } catch (err) {
    update(item.id, { state: 'error', message: toApiError(err).message })
  } finally {
    void qc.invalidateQueries({ queryKey: queryKeys.documents(item.workspaceId) })
  }
}
