import { screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw/http'
import { describe, expect, it } from 'vitest'
import { renderApp } from '@/test/render'
import { API, problem, server, signedIn, testUser, testWorkspace } from '@/test/server'

describe('route guards', () => {
  it('sends a signed-out visitor to login, remembering where they were going', async () => {
    const { router } = renderApp('/w/w1/documents')
    expect(await screen.findByRole('heading', { name: 'Sign in to DocuMind' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent('/w/w1/documents')}`)
  })

  it('opens the last-used or personal workspace at /', async () => {
    server.use(...signedIn())
    const { router } = renderApp('/')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}`))
    expect(await screen.findByRole('heading', { name: /Jan\./ })).toBeInTheDocument()
  })

  it("redirects away from a workspace you aren't a member of", async () => {
    server.use(...signedIn())
    const { router } = renderApp('/w/someone-elses-workspace')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}`))
  })
})

describe('login', () => {
  it('validates before calling the API', async () => {
    const { user } = renderApp('/login')
    await user.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
  })

  it('shows a clear message for wrong credentials', async () => {
    server.use(http.post(`${API}/auth/login`, () => problem(401, 'invalid_credentials', 'Invalid email or password')))
    const { user } = renderApp('/login')
    await user.type(await screen.findByLabelText('Email'), 'jan@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That email and password combination is incorrect.')
  })

  it('signs in and continues to the page that was requested', async () => {
    let signedInNow = false
    server.use(
      http.post(`${API}/auth/login`, () => {
        signedInNow = true
        return HttpResponse.json({ user: testUser, access_expires_at: '2026-11-23T01:00:00Z' })
      }),
      http.get(`${API}/users/me`, () => (signedInNow ? HttpResponse.json(testUser) : problem(401, 'not_authenticated'))),
      http.get(`${API}/workspaces`, () => HttpResponse.json([testWorkspace])),
    )
    const { user, router } = renderApp(`/login?next=${encodeURIComponent('/w/w1/settings')}`)
    await user.type(await screen.findByLabelText('Email'), 'jan@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/w/w1/settings'))
  })

  it('ignores an off-site "next" after login', async () => {
    server.use(
      http.post(`${API}/auth/login`, () => HttpResponse.json({ user: testUser, access_expires_at: '' })),
      http.get(`${API}/workspaces`, () => HttpResponse.json([testWorkspace])),
    )
    const { user, router } = renderApp(`/login?next=${encodeURIComponent('//evil.example')}`)
    await user.type(await screen.findByLabelText('Email'), 'jan@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/w/w1'))
  })
})

describe('register', () => {
  it('puts server-side field errors next to the field', async () => {
    server.use(
      http.post(`${API}/auth/register`, () =>
        HttpResponse.json(
          { status: 422, code: 'validation_error', detail: 'Invalid request', errors: [{ loc: ['body', 'password'], msg: 'Value error, This password is too common' }] },
          { status: 422 },
        ),
      ),
    )
    const { user } = renderApp('/register')
    await user.type(await screen.findByLabelText('Your name'), 'Jan')
    await user.type(screen.getByLabelText('Email'), 'jan@example.com')
    await user.type(screen.getByLabelText('Password'), 'password1234')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('This password is too common')).toBeInTheDocument()
  })
})
