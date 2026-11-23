/**
 * Small client-only UI state (Zustand). Server data stays in TanStack Query - never copied here.
 * Persisted to localStorage: theme choice and the last workspace you opened. No tokens, ever.
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { Theme } from '@/lib/types'

interface PreferencesState {
  theme: Theme
  lastWorkspaceId: string | null
  documentView: 'grid' | 'list'
  setDocumentView: (view: 'grid' | 'list') => void
  setTheme: (theme: Theme) => void
  setLastWorkspaceId: (id: string | null) => void
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: 'system',
      lastWorkspaceId: null,
      documentView: 'grid',
      setDocumentView: (documentView) => set({ documentView }),
      setTheme: (theme) => set({ theme }),
      setLastWorkspaceId: (lastWorkspaceId) => set({ lastWorkspaceId }),
    }),
    {
      name: 'documind-preferences',
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
)

const media = () => window.matchMedia('(prefers-color-scheme: dark)')

export function resolveTheme(theme: Theme): 'light' | 'dark' {
  return theme === 'system' ? (media().matches ? 'dark' : 'light') : theme
}

/** Keeps <html class="dark"> in sync with the preference and the OS setting. */
export function syncThemeWithDocument(): () => void {
  const apply = () => {
    const resolved = resolveTheme(usePreferences.getState().theme)
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }
  apply()
  const unsubscribe = usePreferences.subscribe(apply)
  const mq = media()
  mq.addEventListener('change', apply)
  return () => {
    unsubscribe()
    mq.removeEventListener('change', apply)
  }
}
