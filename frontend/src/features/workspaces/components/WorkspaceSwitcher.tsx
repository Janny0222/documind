import { Check, ChevronsUpDown, FlaskConical, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useWorkspaces } from '@/features/workspaces/api'
import { CreateWorkspaceDialog } from '@/features/workspaces/components/CreateWorkspaceDialog'
import { useOpenDemo } from '@/features/workspaces/use-open-demo'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import type { Workspace } from '@/lib/types'
import { cn } from '@/lib/utils'

export function WorkspaceAvatar({ workspace, className }: { workspace: Pick<Workspace, 'name'>; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'bg-accent text-accent-foreground grid size-6 shrink-0 place-items-center rounded-md text-[0.7rem] font-semibold',
        className,
      )}
    >
      {workspace.name.trim().charAt(0).toUpperCase() || 'W'}
    </span>
  )
}

const roleLabel: Record<Workspace['role'], string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer',
}

export function WorkspaceSwitcher() {
  const current = useCurrentWorkspace()
  const { data: workspaces = [] } = useWorkspaces()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const demo = useOpenDemo()

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            aria-label={`Current workspace: ${current.name}. Switch workspace`}
            className="h-9 max-w-[10rem] min-w-0 justify-start gap-2 px-2 lg:max-w-[14rem]"
          >
            <WorkspaceAvatar workspace={current} />
            <span className="truncate font-medium">{current.name}</span>
            <ChevronsUpDown className="text-muted-foreground ml-auto size-3.5" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-0">
          <Command>
            <CommandInput placeholder="Find a workspace" />
            <CommandList>
              <CommandEmpty>No workspace with that name.</CommandEmpty>
              <CommandGroup heading="Your workspaces">
                {workspaces.map((ws) => (
                  <CommandItem
                    key={ws.id}
                    value={`${ws.name} ${ws.id}`}
                    onSelect={() => {
                      setOpen(false)
                      navigate(`/w/${ws.id}`)
                    }}
                    className="gap-2"
                  >
                    <WorkspaceAvatar workspace={ws} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{ws.name}</span>
                      <span className="text-muted-foreground block text-xs">
                        {roleLabel[ws.role]} · {ws.member_count} {ws.member_count === 1 ? 'member' : 'members'}
                      </span>
                    </span>
                    {ws.id === current.id ? <Check className="text-primary size-4" aria-label="Current" /> : null}
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup>
                <CommandItem
                  onSelect={() => {
                    setOpen(false)
                    setCreating(true)
                  }}
                  className="gap-2"
                >
                  <Plus className="size-4" aria-hidden />
                  Create workspace
                </CommandItem>
                {demo.available && !demo.joined ? (
                  <CommandItem
                    onSelect={() => {
                      setOpen(false)
                      demo.open()
                    }}
                    className="gap-2"
                  >
                    <FlaskConical className="size-4" aria-hidden />
                    Try the demo workspace
                  </CommandItem>
                ) : null}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <CreateWorkspaceDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}
