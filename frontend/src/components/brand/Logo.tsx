import { useId } from 'react'
import { cn } from '@/lib/utils'

export function LogoMark({ className }: { className?: string }) {
  // Unique per instance: two logos on a page (one hidden) must not share a gradient id,
  // or the visible one loses its fill when the hidden one owns the definition.
  const gradientId = useId()
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn('size-7 shrink-0', className)}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--ai-from)" />
          <stop offset="1" stopColor="var(--ai-to)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gradientId})`} />
      <path
        d="M10 8.5h6.2a7.5 7.5 0 0 1 0 15H10z"
        fill="none"
        stroke="#fff"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="16" r="2.4" fill="#fff" />
    </svg>
  )
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <LogoMark />
      <span className="font-heading text-[1.05rem] font-bold tracking-tight">DocuMind</span>
    </span>
  )
}
