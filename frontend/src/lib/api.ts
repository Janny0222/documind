/**
 * The single HTTP client for the DocuMind API.
 *
 * - Same-origin `/api/v1` + `withCredentials`: auth lives in HttpOnly cookies the JS can't read.
 * - CSRF: unsafe requests echo the readable `dm_csrf` cookie in `X-CSRF-Token`.
 * - Session refresh: a 401 triggers ONE shared refresh (single-flight) and the request is
 *   retried once. If refresh fails, listeners are told the session ended.
 * - Errors become `ApiError` with the backend's stable `code` (problem+json).
 */
import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'

export const API_BASE = '/api/v1'
const CSRF_COOKIE = 'dm_csrf'
const SAFE_METHODS = new Set(['get', 'head', 'options'])

// ------------------------------------------------------------------ errors

export interface FieldError {
  field: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: FieldError[]
  readonly retryAfter: number | null

  constructor(opts: {
    status: number
    code: string
    message: string
    fieldErrors?: FieldError[]
    retryAfter?: number | null
  }) {
    super(opts.message)
    this.name = 'ApiError'
    this.status = opts.status
    this.code = opts.code
    this.fieldErrors = opts.fieldErrors ?? []
    this.retryAfter = opts.retryAfter ?? null
  }
}

interface ProblemBody {
  code?: string
  detail?: string
  title?: string
  errors?: { loc?: (string | number)[]; msg?: string }[]
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return new ApiError({
        status: 0,
        code: 'network_error',
        message: "Can't reach DocuMind. Check your connection and try again.",
      })
    }
    const body = (error.response.data ?? {}) as ProblemBody
    const fieldErrors = (body.errors ?? []).map((e) => ({
      // ["body", "email"] -> "email"
      field: String(e.loc?.filter((p) => p !== 'body').join('.') ?? ''),
      message: (e.msg ?? 'Invalid value').replace(/^Value error, /, ''),
    }))
    const retry = Number(error.response.headers?.['retry-after'])
    return new ApiError({
      status: error.response.status,
      code: body.code ?? 'http_error',
      message: body.detail ?? body.title ?? 'Something went wrong. Please try again.',
      fieldErrors,
      retryAfter: Number.isFinite(retry) ? retry : null,
    })
  }
  return new ApiError({ status: 0, code: 'unknown', message: 'Something went wrong.' })
}

// ------------------------------------------------------------------ cookies / csrf

export function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

let csrfPromise: Promise<void> | null = null

async function ensureCsrf(): Promise<string | null> {
  if (!readCookie(CSRF_COOKIE)) {
    csrfPromise ??= raw.get('/auth/csrf').then(
      () => undefined,
      () => undefined,
    )
    await csrfPromise
    csrfPromise = null
  }
  return readCookie(CSRF_COOKIE)
}

// ------------------------------------------------------------------ session-ended events

type Listener = () => void
const sessionEndedListeners = new Set<Listener>()

/** Called when the session can't be refreshed (expired, revoked, or logged out elsewhere). */
export function onSessionEnded(listener: Listener): () => void {
  sessionEndedListeners.add(listener)
  return () => sessionEndedListeners.delete(listener)
}

// ------------------------------------------------------------------ clients

/** Bare client: no refresh logic (used for /auth/csrf and /auth/refresh themselves). */
const raw = axios.create({ baseURL: API_BASE, withCredentials: true })

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { Accept: 'application/json' },
})

async function attachCsrf(config: InternalAxiosRequestConfig) {
  if (!SAFE_METHODS.has((config.method ?? 'get').toLowerCase())) {
    const token = await ensureCsrf()
    if (token) {
      const headers = AxiosHeaders.from(config.headers)
      headers.set('X-CSRF-Token', token)
      config.headers = headers
    }
  }
  return config
}

api.interceptors.request.use(attachCsrf)
raw.interceptors.request.use(attachCsrf)

// Requests that must never trigger a refresh-and-retry loop.
const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout', '/auth/csrf']

let refreshPromise: Promise<boolean> | null = null

/** One refresh for any number of concurrent 401s. Resolves true when the session is alive. */
export function refreshSession(): Promise<boolean> {
  refreshPromise ??= raw
    .post('/auth/refresh')
    .then(() => true)
    .catch(async (err: unknown) => {
      // Another tab rotated the token a moment ago; its new cookie is already ours.
      if (toApiError(err).code === 'refresh_race') {
        await new Promise((r) => setTimeout(r, 300))
        return true
      }
      return false
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

type RetriableConfig = AxiosRequestConfig & { _retried?: boolean }

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const url = config?.url ?? ''
    if (
      error.response?.status === 401 &&
      config &&
      !config._retried &&
      !NO_REFRESH.some((p) => url.startsWith(p))
    ) {
      config._retried = true
      if (await refreshSession()) return api.request(config)
      sessionEndedListeners.forEach((l) => l())
    }
    throw toApiError(error)
  },
)

/** Typed helpers so feature code reads like `await http.get<User>('/users/me')`. */
export const http = {
  get: async <T>(url: string, config?: AxiosRequestConfig) =>
    (await api.get<T>(url, config)).data,
  post: async <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    (await api.post<T>(url, body, config)).data,
  patch: async <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    (await api.patch<T>(url, body, config)).data,
  put: async <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    (await api.put<T>(url, body, config)).data,
  delete: async <T>(url: string, body?: unknown) =>
    (await api.delete<T>(url, { data: body })).data,
}
