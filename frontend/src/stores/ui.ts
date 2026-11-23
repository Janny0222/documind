import { create } from 'zustand'

interface UiState {
  commandOpen: boolean
  setCommandOpen: (open: boolean) => void
}

export const useUi = create<UiState>()((set) => ({
  commandOpen: false,
  setCommandOpen: (commandOpen) => set({ commandOpen }),
}))

export const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
