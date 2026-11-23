import { HttpResponse, http } from 'msw/http'
import { setupServer } from 'msw/node'
import type { User, Workspace } from '@/lib/types'

export const API = '*/api/v1'

export const testUser: User = {
  id: 'u1',
  email: 'jan@example.com',
  display_name: 'Jan Reyes',
  email_verified: true,
  theme: 'system',
  created_at: '2026-11-23T00:00:00Z',
}

export const testWorkspace: Workspace = {
  id: 'w1',
  name: "Jan's Workspace",
  role: 'owner',
  is_personal: true,
  is_demo: false,
  ai_consent: false,
  member_count: 1,
  created_at: '2026-11-23T00:00:00Z',
}

export const problem = (status: number, code: string, detail = code) =>
  HttpResponse.json({ status, code, detail, title: detail }, { status, headers: { 'Content-Type': 'application/problem+json' } })

/** Default: a signed-out visitor. Tests opt into other states with server.use(...). */
export const server = setupServer(
  http.get(`${API}/auth/csrf`, () => HttpResponse.json({ csrf_token: 'test-csrf' })),
  http.get(`${API}/users/me`, () => problem(401, 'not_authenticated')),
  http.post(`${API}/auth/refresh`, () => problem(401, 'session_expired')),
)

export const signedIn = (user: User = testUser, workspaces: Workspace[] = [testWorkspace]) => [
  http.get(`${API}/users/me`, () => HttpResponse.json(user)),
  http.get(`${API}/workspaces`, () => HttpResponse.json(workspaces)),
  http.get(`${API}/workspaces/:id/documents`, () =>
    HttpResponse.json({ items: [], total: 0, counts: { all: 0, pdf: 0, docx: 0, txt: 0 } }),
  ),
  http.get(`${API}/workspaces/:id/collections`, () => HttpResponse.json([])),
  http.get(`${API}/notifications`, () => HttpResponse.json({ items: [], unread: 0 })),
  http.get(`${API}/demo`, () => HttpResponse.json({ available: false, joined: false, workspace_id: null })),
  http.get(`${API}/workspaces/:id/members`, () =>
    HttpResponse.json([
      { user_id: user.id, email: user.email, display_name: user.display_name, role: 'owner', joined_at: user.created_at },
    ]),
  ),
]
