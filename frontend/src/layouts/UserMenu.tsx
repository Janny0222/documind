import { BarChart3, Check, LogOut, Monitor, Moon, Settings, Sun, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useLogout, useMe, useUpdateProfile } from '@/features/auth/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { atLeast, type Theme } from '@/lib/types'
import { initials } from '@/lib/format'
import { usePreferences } from '@/stores/preferences'

const themes: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export function UserMenu() {
  const { data: user } = useMe()
  const workspace = useCurrentWorkspace()
  const navigate = useNavigate()
  const logout = useLogout()
  const updateProfile = useUpdateProfile()
  const theme = usePreferences((s) => s.theme)
  const setTheme = usePreferences((s) => s.setTheme)
  if (!user) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="focus-visible:ring-ring rounded-full outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
        aria-label="Account menu"
      >
        <Avatar className="size-8">
          <AvatarFallback className="bg-accent text-accent-foreground text-xs font-semibold">
            {initials(user.display_name)}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate font-medium">{user.display_name}</p>
          <p className="text-muted-foreground truncate text-xs">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onSelect={() => navigate(wsPath(workspace.id, 'settings/account'))}>
            <UserRound aria-hidden /> Your account
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => navigate(wsPath(workspace.id, 'settings'))}>
            <Settings aria-hidden /> Workspace settings
          </DropdownMenuItem>
          {atLeast(workspace.role, 'admin') ? (
            <DropdownMenuItem onSelect={() => navigate(wsPath(workspace.id, 'analytics'))}>
              <BarChart3 aria-hidden /> Usage & analytics
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Theme</DropdownMenuLabel>
        {themes.map((t) => (
          <DropdownMenuItem
            key={t.value}
            onSelect={(e) => {
              e.preventDefault()
              setTheme(t.value)
              updateProfile.mutate({ theme: t.value })
            }}
          >
            <t.icon aria-hidden /> {t.label}
            {theme === t.value ? <Check className="text-primary ml-auto" aria-label="Selected" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}>
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
