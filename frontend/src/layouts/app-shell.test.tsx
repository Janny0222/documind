import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '@/test/render'
import { server, signedIn, testWorkspace } from '@/test/server'

async function openPalette() {
  server.use(...signedIn())
  const app = renderApp(`/w/${testWorkspace.id}`)
  await screen.findByRole('heading', { name: /Jan\./ })
  await app.user.keyboard('{Control>}k{/Control}')
  const dialog = await screen.findByRole('dialog')
  return { ...app, dialog }
}

describe('command palette', () => {
  // Regression: shadcn v4's CommandDialog doesn't include the cmdk root; items crashed the page.
  it('opens with Ctrl+K and lists navigation', async () => {
    const { dialog } = await openPalette()
    expect(within(dialog).getByRole('option', { name: /Documents/ })).toBeInTheDocument()
    expect(within(dialog).getByRole('option', { name: /Light theme/ })).toBeInTheDocument()
  })

  // Regression: "light" used to select "Ask “light”" instead of the Light theme command.
  it('ranks real commands above the free-text Ask item', async () => {
    const { dialog, user } = await openPalette()
    await user.type(within(dialog).getByRole('combobox'), 'light')
    const options = within(dialog).getAllByRole('option')
    expect(options[0]).toHaveTextContent('Light theme')
    // Free-text items (ask / search passages) always come after real commands.
    expect(options.slice(-2).map((o) => o.textContent)).toEqual(['Ask “light”', 'Search passages for “light”'])
  })

  it('sends a question that matches no command to the Ask page', async () => {
    const { dialog, user, router } = await openPalette()
    await user.type(within(dialog).getByRole('combobox'), 'what are the payment terms{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}/ask`))
    expect(router.state.location.search).toBe('?q=what%20are%20the%20payment%20terms')
  })
})

describe('dashboard ask bar', () => {
  it('hands the question to the AI workspace when Enter is pressed', async () => {
    server.use(...signedIn())
    const { user, router } = renderApp(`/w/${testWorkspace.id}`)
    const input = await screen.findByLabelText('Ask your documents a question')
    await user.type(input, 'When are invoices due?{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${testWorkspace.id}/ask`))
    expect(router.state.location.search).toBe('?q=When%20are%20invoices%20due%3F')
  })
})
