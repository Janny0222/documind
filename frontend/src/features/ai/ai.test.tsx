import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw/http'
import { describe, expect, it, vi } from 'vitest'
import { AnswerText } from '@/features/ai/AnswerText'
import { createSseParser } from '@/features/ai/stream'
import type { ChatMessage, Citation } from '@/lib/types'
import { renderApp } from '@/test/render'
import { API, server, signedIn, testWorkspace } from '@/test/server'

// Offsets are computed from the page text, exactly as the indexer stores them.
const PAGE_TEXT = 'Section 7. Employees give thirty (30) days written notice before resigning. Managers give sixty.'
const CITED = 'Employees give thirty (30) days written notice before resigning.'

const citation: Citation = {
  marker: 'S1',
  document_id: 'd1',
  document_title: 'Employee Handbook',
  page_number: 2,
  page_unit: 'page',
  excerpt: 'Employees give thirty (30) days written notice before resigning.',
  chunk_id: 'c1',
  char_start: PAGE_TEXT.indexOf(CITED),
  char_end: PAGE_TEXT.indexOf(CITED) + CITED.length,
}

describe('SSE parser', () => {
  it('handles events split across network chunks', () => {
    const seen: [string, string][] = []
    const feed = createSseParser((e, d) => seen.push([e, d]))
    feed('event: token\ndata: {"text":"Hel')
    feed('lo"}\n\nevent: done\r\n')
    feed('data: {}\r\n\r\n')
    expect(seen).toEqual([
      ['token', '{"text":"Hello"}'],
      ['done', '{}'],
    ])
  })
})

describe('AnswerText', () => {
  it('renders verified citations as numbered buttons and hides unverified markers', async () => {
    const onCite = vi.fn()
    render(<AnswerText text={'Notice is **30 days** [S1]. Made up [S4].'} citations={[citation]} onCite={onCite} />)
    expect(screen.getByText('30 days').tagName).toBe('STRONG')
    const chip = screen.getByRole('button', { name: /Source 1: Employee Handbook, page 2/ })
    await userEvent.click(chip)
    expect(onCite).toHaveBeenCalledWith(citation)
    expect(screen.queryByText(/\[S4\]/)).not.toBeInTheDocument()
  })

  it('never renders model or document text as HTML', () => {
    const { container } = render(<AnswerText text={'<img src=x onerror="alert(1)"> hi'} citations={[]} onCite={() => {}} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)"> hi')
  })

  it('renders bullet lists', () => {
    render(<AnswerText text={'Benefits:\n- Health insurance [S1]\n- Dental'} citations={[citation]} onCite={() => {}} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })
})

const sse = (events: [string, unknown][]) =>
  new HttpResponse(events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream' },
  })

describe('AI workspace', () => {
  it('asks, streams the answer, and opens the cited passage', async () => {
    const answer: ChatMessage = {
      id: 'm2',
      role: 'assistant',
      content: 'Employees give thirty days notice [S1].',
      status: 'complete',
      created_at: new Date().toISOString(),
      citations: [citation],
    }
    let asked = false
    server.use(
      http.get(`${API}/workspaces/:id/ai/status`, () =>
        HttpResponse.json({ configured: true, consent: true, questions_left_today: 29, daily_limit: 30, chat_model: 'm' }),
      ),
      http.get(`${API}/workspaces/:id/conversations`, () => HttpResponse.json([])),
      http.post(`${API}/workspaces/:id/conversations`, () =>
        HttpResponse.json({ id: 'conv1', title: 'New conversation', scope: { type: 'workspace' }, created_at: '', updated_at: '' }, { status: 201 }),
      ),
      http.post(`${API}/workspaces/:id/conversations/conv1/messages`, () => {
        asked = true
        return sse([
          ['meta', { user_message_id: 'm1', assistant_message_id: 'm2' }],
          ['retrieval', { documents: 1, passages: 2 }],
          ['token', { text: 'Employees give thirty ' }],
          ['token', { text: 'days notice [S1].' }],
          ['citations', [citation]],
          ['suggestions', ['Do managers give more notice?']],
          ['done', { message: answer }],
        ])
      }),
      http.get(`${API}/workspaces/:id/conversations/conv1`, () =>
        HttpResponse.json({
          id: 'conv1',
          title: 'How much notice?',
          scope: { type: 'workspace' },
          created_at: '',
          updated_at: '',
          messages: asked
            ? [{ id: 'm1', role: 'user', content: 'How much notice?', status: 'complete', created_at: '', citations: [] }, answer]
            : [],
        }),
      ),
      http.get(`${API}/workspaces/:id/documents/d1/pages/2`, () =>
        HttpResponse.json({
          page_number: 2,
          page_count: 3,
          page_unit: 'page',
          text: PAGE_TEXT,
        }),
      ),
      ...signedIn(),
    )
    document.cookie = 'dm_csrf=t; path=/'
    const { user, router } = renderApp(`/w/${testWorkspace.id}/ask`)
    const input = await screen.findByLabelText('Ask a question about your documents', {}, { timeout: 5000 })
    await waitFor(() => expect(input).toBeEnabled()) // enabled once AI status says we can ask
    await user.type(input, 'How much notice?{Enter}')

    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}/ask/conv1`))
    expect(await screen.findByText('Do managers give more notice?')).toBeInTheDocument()
    const chip = await screen.findByRole('button', { name: /Source 1: Employee Handbook, page 2/ })
    await user.click(chip)

    const panel = await screen.findByRole('complementary', { name: 'Source' })
    const highlighted = await within(panel).findByText(CITED, { selector: 'mark' })
    expect(highlighted).toHaveTextContent(CITED) // exactly the cited span, nothing more
  })

  it('explains when AI processing has not been allowed', async () => {
    server.use(
      http.get(`${API}/workspaces/:id/ai/status`, () =>
        HttpResponse.json({ configured: true, consent: false, questions_left_today: 30, daily_limit: 30, chat_model: 'm' }),
      ),
      http.get(`${API}/workspaces/:id/conversations`, () => HttpResponse.json([])),
      ...signedIn(),
    )
    renderApp(`/w/${testWorkspace.id}/ask`)
    expect(await screen.findByText(/sent to Google Gemini/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Allow AI processing/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Ask a question about your documents')).toBeDisabled()
  })
})
