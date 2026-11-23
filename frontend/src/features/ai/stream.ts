/**
 * Server-Sent Events over a POST request. EventSource only supports GET and can't send our
 * CSRF header, so we use fetch() + a small incremental parser instead.
 */
import { ApiError, API_BASE, readCookie, refreshSession } from '@/lib/api'
import type { ChatMessage, Citation } from '@/lib/types'

export interface StreamHandlers {
  onMeta?: (data: { user_message_id: string; assistant_message_id: string }) => void
  onRetrieval?: (data: { documents: number; passages: number }) => void
  onToken?: (text: string) => void
  onCitations?: (citations: Citation[]) => void
  onSuggestions?: (suggestions: string[]) => void
  onDone?: (message: ChatMessage) => void
  onError?: (error: { code: string; message: string }) => void
}

/** Splits a text/event-stream into {event, data} pairs. Handles events split across chunks. */
export function createSseParser(onEvent: (event: string, data: string) => void) {
  let buffer = ''
  return (chunk: string) => {
    buffer += chunk.replace(/\r\n/g, '\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length) onEvent(event, data.join('\n'))
    }
  }
}

async function post(path: string, body: unknown, signal?: AbortSignal) {
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-CSRF-Token': readCookie('dm_csrf') ?? '',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
}

export async function streamAnswer(path: string, body: unknown, handlers: StreamHandlers, signal?: AbortSignal) {
  let res = await post(path, body, signal)
  if (res.status === 401 && (await refreshSession())) res = await post(path, body, signal)
  if (!res.ok || !res.body) {
    const problem = (await res.json().catch(() => ({}))) as { code?: string; detail?: string }
    throw new ApiError({
      status: res.status,
      code: problem.code ?? 'http_error',
      message: problem.detail ?? 'Something went wrong. Please try again.',
      retryAfter: Number(res.headers.get('retry-after')) || null,
    })
  }

  const parse = createSseParser((event, raw) => {
    const data = JSON.parse(raw) as never
    switch (event) {
      case 'meta':
        return handlers.onMeta?.(data)
      case 'retrieval':
        return handlers.onRetrieval?.(data)
      case 'token':
        return handlers.onToken?.((data as { text: string }).text)
      case 'citations':
        return handlers.onCitations?.(data)
      case 'suggestions':
        return handlers.onSuggestions?.(data)
      case 'done':
        return handlers.onDone?.((data as { message: ChatMessage }).message)
      case 'error':
        return handlers.onError?.(data)
    }
  })

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    parse(value)
  }
}
