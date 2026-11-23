import { screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw/http'
import { describe, expect, it } from 'vitest'
import { renderApp } from '@/test/render'
import { API, server, signedIn, testWorkspace } from '@/test/server'

const demoWs = { ...testWorkspace, id: 'demo1', name: 'Demo: Lumen & Pine', is_personal: false, is_demo: true, role: 'viewer' as const, ai_consent: true }

describe('demo workspace', () => {
  it('joins the demo from an empty dashboard and shows the demo banner', async () => {
    let joined = false
    server.use(
      http.get(`${API}/demo`, () => HttpResponse.json({ available: true, joined, workspace_id: 'demo1' })),
      http.post(`${API}/demo/join`, () => {
        joined = true
        return HttpResponse.json({ workspace_id: 'demo1' })
      }),
      http.get(`${API}/workspaces`, () => HttpResponse.json(joined ? [testWorkspace, demoWs] : [testWorkspace])),
      ...signedIn(),
    )
    document.cookie = 'dm_csrf=t; path=/'
    const { user, router } = renderApp(`/w/${testWorkspace.id}`)
    await user.click(await screen.findByRole('button', { name: 'Try the demo workspace' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/w/demo1'))
    expect(await screen.findByRole('note')).toHaveTextContent('Demo workspace.')
    expect(screen.getByRole('heading', { name: 'Questions to try' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Set up this workspace' })).not.toBeInTheDocument()
  })

  it('hides the demo entry when the server has no demo', async () => {
    server.use(...signedIn())
    renderApp(`/w/${testWorkspace.id}`)
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try the demo workspace' })).not.toBeInTheDocument()
  })
})
