import { LogOut, Monitor, Moon, Plus, Search as SearchIcon, Sparkles, Sun, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { defaultFilter } from 'cmdk'
import { useNavigate } from 'react-router'
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { useLogout, useUpdateProfile } from '@/features/auth/api'
import { useWorkspaces } from '@/features/workspaces/api'
import { CreateWorkspaceDialog } from '@/features/workspaces/components/CreateWorkspaceDialog'
import { WorkspaceAvatar } from '@/features/workspaces/components/WorkspaceSwitcher'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { analyticsNav, primaryNav, settingsNav, wsPath } from '@/layouts/nav'
import { atLeast, type Theme } from '@/lib/types'
import { usePreferences } from '@/stores/preferences'
import { useUi } from '@/stores/ui'

/**
 * The free-text "Ask" item matches every query, so give it a tiny score: real commands
 * ("light" -> Light theme) always win, and Ask is only on top when nothing else matches.
 */
const rankCommandsAboveAsk = (value: string, search: string, keywords?: string[]) =>
  value.startsWith("ask ") ? 0.001 : defaultFilter(value, search, keywords)

/** ⌘K / Ctrl+K: jump anywhere, switch workspace, change theme, or start a question. */
export function CommandPalette() {
  const open = useUi((s) => s.commandOpen)
  const setOpen = useUi((s) => s.setCommandOpen)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const { data: workspaces = [] } = useWorkspaces()
  const logout = useLogout()
  const updateProfile = useUpdateProfile()
  const setTheme = usePreferences((s) => s.setTheme)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen(!useUi.getState().commandOpen)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setOpen])

  const run = (fn: () => void) => {
    setOpen(false)
    setSearch('')
    fn()
  }

  const chooseTheme = (theme: Theme) => {
    setTheme(theme) // instant locally
    updateProfile.mutate({ theme }) // remembered across devices
  }

  const question = search.trim()

  return (
    <>
      <CommandDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o)
          if (!o) setSearch('')
        }}
        title="Command palette"
        description="Jump to a page, switch workspace, or ask your documents a question."
      >
        {/* shadcn v4: CommandDialog no longer includes the cmdk root - it must be added here. */}
        <Command filter={rankCommandsAboveAsk}>
        <CommandInput placeholder="Search, jump to, or ask…" value={search} onValueChange={setSearch} />
        <CommandList>
          <CommandEmpty>Nothing matches. Type a few more words to ask it as a question.</CommandEmpty>
          <CommandGroup heading="Go to">
            {[...primaryNav, settingsNav, ...(atLeast(workspace.role, 'admin') ? [analyticsNav] : [])].map((item) => (
              <CommandItem key={item.label} onSelect={() => run(() => navigate(wsPath(workspace.id, item.to)))}>
                <item.icon aria-hidden />
                {item.label}
              </CommandItem>
            ))}
            <CommandItem onSelect={() => run(() => navigate(wsPath(workspace.id, 'settings/account')))}>
              <UserRound aria-hidden />
              Your account
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Workspaces">
            {workspaces
              .filter((w) => w.id !== workspace.id)
              .map((w) => (
                <CommandItem key={w.id} value={`switch ${w.name} ${w.id}`} onSelect={() => run(() => navigate(`/w/${w.id}`))}>
                  <WorkspaceAvatar workspace={w} className="size-5" />
                  Switch to {w.name}
                </CommandItem>
              ))}
            <CommandItem onSelect={() => run(() => setCreating(true))}>
              <Plus aria-hidden />
              Create workspace
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Appearance">
            <CommandItem onSelect={() => run(() => chooseTheme('light'))}>
              <Sun aria-hidden /> Light theme
            </CommandItem>
            <CommandItem onSelect={() => run(() => chooseTheme('dark'))}>
              <Moon aria-hidden /> Dark theme
            </CommandItem>
            <CommandItem onSelect={() => run(() => chooseTheme('system'))}>
              <Monitor aria-hidden /> Match system theme
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup>
            <CommandItem onSelect={() => run(() => logout.mutate(undefined, { onSettled: () => navigate('/login') }))}>
              <LogOut aria-hidden />
              Sign out
            </CommandItem>
          </CommandGroup>
          {/* Last on purpose: commands come first; Ask catches everything else. */}
          {question.length > 2 ? (
            <CommandGroup heading="Ask">
              <CommandItem
                value={`ask ${question}`}
                onSelect={() =>
                  run(() => navigate(`${wsPath(workspace.id, 'ask')}?q=${encodeURIComponent(question)}`))
                }
              >
                <Sparkles className="text-primary" aria-hidden />
                <span className="truncate">Ask “{question}”</span>
              </CommandItem>
              <CommandItem
                value={`ask search ${question}`}
                onSelect={() =>
                  run(() => navigate(`${wsPath(workspace.id, 'search')}?q=${encodeURIComponent(question)}`))
                }
              >
                <SearchIcon aria-hidden />
                <span className="truncate">Search passages for “{question}”</span>
              </CommandItem>
            </CommandGroup>
          ) : null}
        </CommandList>
        </Command>
      </CommandDialog>
      <CreateWorkspaceDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}
