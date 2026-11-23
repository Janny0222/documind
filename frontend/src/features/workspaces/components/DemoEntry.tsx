import { FlaskConical, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { useOpenDemo } from '@/features/workspaces/use-open-demo'

export function TryDemoButton({ variant = 'outline' }: { variant?: 'outline' | 'ghost' }) {
  const demo = useOpenDemo()
  if (!demo.available) return null
  return (
    <Button variant={variant} onClick={demo.open} disabled={demo.pending}>
      {demo.pending ? <Loader2 className="animate-spin" aria-hidden /> : <FlaskConical aria-hidden />}
      Try the demo workspace
    </Button>
  )
}

/** Shown on every page of the demo workspace so nobody mistakes it for their own. */
export function DemoBanner() {
  const workspace = useCurrentWorkspace()
  if (!workspace.is_demo) return null
  return (
    <div role="note" className="bg-accent text-accent-foreground border-b">
      <p className="mx-auto flex max-w-[1240px] items-center gap-2 px-4 py-2 text-sm sm:px-6">
        <FlaskConical className="size-4 shrink-0" aria-hidden />
        <span>
          <span className="font-medium">Demo workspace.</span> Sample documents about a made-up company. Read-only,
          10 questions a day, and conversations are cleared every night.
        </span>
      </p>
    </div>
  )
}
