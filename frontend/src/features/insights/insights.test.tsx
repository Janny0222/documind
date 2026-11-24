import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw/http'
import { describe, expect, it } from 'vitest'
import type { Analytics, Notification } from '@/features/insights/api'
import { renderApp } from '@/test/render'
import { API, server, signedIn, testWorkspace } from '@/test/server'

const team = { ...testWorkspace, is_personal: false, name: 'Acme' }

describe('notification bell', () => {
  it('shows the unread count and marks everything read', async () => {
    let unread = true
    const note: Notification = {
      id: 'n1',
      type: 'document_ready',
      title: '“Handbook” is ready',
      body: '3 pages indexed.',
      link: '/w/w1/documents?doc=d1',
      invitation_id: null,
      workspace_id: 'w1',
      read: false,
      created_at: new Date().toISOString(),
    }
    let marked: unknown = null
    server.use(
      http.get(`${API}/notifications`, () => HttpResponse.json({ items: [{ ...note, read: !unread }], unread: unread ? 1 : 0 })),
      http.post(`${API}/notifications/read`, async ({ request }) => {
        marked = await request.json()
        unread = false
        return HttpResponse.json({ updated: 1 })
      }),
      ...signedIn(),
    )
    document.cookie = 'dm_csrf=t; path=/'
    const { user } = renderApp(`/w/${testWorkspace.id}`)
    const bell = await screen.findByRole('button', { name: 'Notifications, 1 unread' })
    await user.click(bell)
    expect(await screen.findByText('“Handbook” is ready')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Mark all as read' }))
    await waitFor(() => expect(marked).toEqual({}))
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
  })
})

describe('search page', () => {
  it('searches from the URL and opens the passage in context', async () => {
    const text = 'Employees give thirty (30) days written notice before resigning.'
    const page = `Section 7. ${text} Managers give sixty.`
    server.use(
      http.post(`${API}/workspaces/:id/search`, async ({ request }) => {
        const body = (await request.json()) as { query: string }
        return HttpResponse.json({
          query: body.query,
          mode: 'hybrid',
          hits: [
            {
              chunk_id: 'c1', document_id: 'd1', document_title: 'Employee Handbook', file_type: 'pdf',
              page_number: 2, page_unit: 'page', char_start: page.indexOf(text), char_end: page.indexOf(text) + text.length,
              text, score: 0.03, similarity: 0.71, keyword_match: true,
            },
          ],
        })
      }),
      http.get(`${API}/workspaces/:id/documents/d1/pages/2`, () =>
        HttpResponse.json({ page_number: 2, page_count: 3, page_unit: 'page', text: page }),
      ),
      ...signedIn(),
    )
    document.cookie = 'dm_csrf=t; path=/'
    const { user } = renderApp(`/w/${testWorkspace.id}/search?q=notice`)
    expect(await screen.findByText('1 passage')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Employee Handbook/ }))
    const panel = await screen.findByRole('complementary', { name: 'Source' })
    expect(await within(panel).findByText(text, { selector: 'mark' })).toBeInTheDocument()
  })
})

const analytics: Analytics = {
  days: 7,
  since: '2026-11-17',
  totals: { questions: 12, answered: 9, not_found: 3, failed: 0, rate_limited: 0, input_tokens: 7300, output_tokens: 610, est_cost_usd: 0 },
  daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-11-${17 + i}`, questions: i, input_tokens: i * 600, output_tokens: i * 50 })),
  by_operation: [{ operation: 'chat', calls: 12, input_tokens: 7000, output_tokens: 610, errors: 0 }],
  documents: { total: 3, ready: 2, processing: 0, failed: 1, storage_bytes: 52_000, by_type: { pdf: 2, docx: 1, txt: 0 }, uploads_in_range: 3 },
  top_members: [{ user_id: 'u1', display_name: 'Jan Reyes', questions: 12 }],
  recent_errors: [],
  limits: { daily_questions_per_user: 30 },
}

describe('analytics', () => {
  it('shows KPIs, charts with a table view, and labels cost as an estimate', async () => {
    server.use(http.get(`${API}/workspaces/:id/analytics`, () => HttpResponse.json(analytics)), ...signedIn(undefined, [team]))
    const { user } = renderApp(`/w/${testWorkspace.id}/analytics`)
    // The page lazy-loads Recharts; on a cold cache (CI) transforming it alone can take several seconds.
    expect(await screen.findByRole('heading', { name: 'Usage & analytics' }, { timeout: 15_000 })).toBeInTheDocument()
    expect(await screen.findByText('75%')).toBeInTheDocument() // 9 of 12 answered from documents
    expect(screen.getByText(/not a bill/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /12 in total/ })).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'View as table' })[0] as HTMLElement)
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(8) // header + 7 days
  })

  it('sends non-admins back home', async () => {
    server.use(...signedIn(undefined, [{ ...team, role: 'member' }]))
    const { router } = renderApp(`/w/${testWorkspace.id}/analytics`)
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}`))
  })
})
