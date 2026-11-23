import { HttpResponse, http as mock } from 'msw/http'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, http, onSessionEnded } from '@/lib/api'
import { API, problem, server } from '@/test/server'

describe('api client', () => {
  it('sends the CSRF cookie back as a header on unsafe requests', async () => {
    document.cookie = 'dm_csrf=abc123; path=/'
    let header: string | null = null
    server.use(
      mock.post(`${API}/workspaces`, ({ request }) => {
        header = request.headers.get('X-CSRF-Token')
        return HttpResponse.json({ id: 'w2' })
      }),
    )
    await http.post('/workspaces', { name: 'X' })
    expect(header).toBe('abc123')
  })

  it('fetches a CSRF token first when the cookie is missing', async () => {
    const order: string[] = []
    server.use(
      mock.get(`${API}/auth/csrf`, () => {
        order.push('csrf')
        document.cookie = 'dm_csrf=fresh; path=/' // what the real Set-Cookie would do
        return HttpResponse.json({ csrf_token: 'fresh' })
      }),
      mock.post(`${API}/workspaces`, ({ request }) => {
        order.push(`post:${request.headers.get('X-CSRF-Token')}`)
        return HttpResponse.json({})
      }),
    )
    await http.post('/workspaces', { name: 'X' })
    expect(order).toEqual(['csrf', 'post:fresh'])
  })

  it('refreshes once for concurrent 401s, then retries each request', async () => {
    document.cookie = 'dm_csrf=t; path=/'
    let refreshed = 0
    let sessionValid = false
    server.use(
      mock.post(`${API}/auth/refresh`, () => {
        refreshed += 1
        sessionValid = true
        return HttpResponse.json({ user: {}, access_expires_at: '' })
      }),
      mock.get(`${API}/things/:id`, ({ params }) =>
        sessionValid ? HttpResponse.json({ id: params.id }) : problem(401, 'session_expired'),
      ),
    )
    const results = await Promise.all([http.get('/things/1'), http.get('/things/2'), http.get('/things/3')])
    expect(results).toEqual([{ id: '1' }, { id: '2' }, { id: '3' }])
    expect(refreshed).toBe(1)
  })

  it('announces the end of the session when refresh fails', async () => {
    document.cookie = 'dm_csrf=t; path=/'
    server.use(mock.get(`${API}/things`, () => problem(401, 'session_expired')))
    const listener = vi.fn()
    const off = onSessionEnded(listener)
    await expect(http.get('/things')).rejects.toMatchObject({ status: 401, code: 'session_expired' })
    expect(listener).toHaveBeenCalledOnce()
    off()
  })

  it('turns problem+json into ApiError with field errors', async () => {
    server.use(
      mock.post(`${API}/auth/register`, () =>
        HttpResponse.json(
          {
            status: 422,
            code: 'validation_error',
            detail: 'Invalid request',
            errors: [{ loc: ['body', 'password'], msg: 'Value error, This password is too common' }],
          },
          { status: 422 },
        ),
      ),
    )
    const err = await http.post('/auth/register', {}).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).fieldErrors).toEqual([{ field: 'password', message: 'This password is too common' }])
  })
})
