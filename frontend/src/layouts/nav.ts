import { BarChart3, FileText, FolderOpen, Home, type LucideIcon, Search, Settings, Sparkles } from 'lucide-react'

export interface NavItem {
  label: string
  /** Path relative to /w/:workspaceId */
  to: string
  icon: LucideIcon
  end?: boolean
}

// Top navigation. Analytics lives in the account menu / command palette (admins): it shouldn't
// dominate everyday use (Phase 1 §13).
export const primaryNav: NavItem[] = [
  { label: 'Home', to: '', icon: Home, end: true },
  { label: 'Documents', to: 'documents', icon: FileText },
  { label: 'Collections', to: 'collections', icon: FolderOpen },
  { label: 'Search', to: 'search', icon: Search },
  { label: 'Ask AI', to: 'ask', icon: Sparkles },
]

export const settingsNav: NavItem = { label: 'Settings', to: 'settings', icon: Settings }

export const analyticsNav: NavItem = { label: 'Usage & analytics', to: 'analytics', icon: BarChart3 }

/** Five thumb-reachable tabs on phones; Search is in the top bar's search button. */
export const mobileNav: NavItem[] = [
  { label: 'Home', to: '', icon: Home, end: true },
  { label: 'Docs', to: 'documents', icon: FileText },
  { label: 'Collections', to: 'collections', icon: FolderOpen },
  { label: 'Ask', to: 'ask', icon: Sparkles },
  { label: 'Settings', to: 'settings', icon: Settings },
]

export const wsPath = (workspaceId: string, to: string) => `/w/${workspaceId}${to ? `/${to}` : ''}`
