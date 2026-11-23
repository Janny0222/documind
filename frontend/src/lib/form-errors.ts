import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { toApiError } from '@/lib/api'

/**
 * Pushes backend validation errors onto matching form fields and returns a message for
 * anything that isn't tied to a field (shown as a form-level alert).
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly Path<T>[],
  overrides: Record<string, string> = {},
): string | null {
  const err = toApiError(error)
  let unmatched = false
  for (const fe of err.fieldErrors) {
    const field = fields.find((f) => f === fe.field || fe.field.endsWith(`.${f}`))
    if (field) setError(field, { type: 'server', message: fe.message })
    else unmatched = true
  }
  if (err.fieldErrors.length > 0 && !unmatched) return null
  if (err.code === 'rate_limited' && err.retryAfter) {
    const minutes = Math.ceil(err.retryAfter / 60)
    return `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`
  }
  return overrides[err.code] ?? err.message
}

/** Reads `#token=...` from the URL, then removes it so it isn't left in history or screenshots. */
export function takeHashToken(): string | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const token = params.get('token')
  if (token) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return token
}
