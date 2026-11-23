import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { usePreferences } from '@/stores/preferences'
import { useUi } from '@/stores/ui'
import { server } from '@/test/server'

// Zustand stores are module singletons: snapshot them once and restore after every test,
// so UI state (e.g. an open command palette) never leaks from one test into the next.
const initialUi = useUi.getInitialState()
const initialPreferences = usePreferences.getInitialState()

// findBy*/waitFor default to 1s, which is too tight when test files run in parallel on a busy
// machine or CI runner (lazy route chunks load during the test). Real failures still fail.
configure({ asyncUtilTimeout: 5000 })

// MSW 3 renamed onUnhandledRequest -> onUnhandledFrame. Any un-mocked request fails the test.
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  server.resetHandlers()
  cleanup()
  useUi.setState(initialUi, true)
  usePreferences.setState(initialPreferences, true)
  localStorage.clear()
  sessionStorage.clear()
  document.cookie.split('; ').forEach((c) => {
    const name = c.split('=')[0]
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`
  })
})
afterAll(() => server.close())

// jsdom lacks these browser APIs used by Radix/cmdk and our theme sync.
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= () => {}
