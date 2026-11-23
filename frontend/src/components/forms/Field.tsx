import { Eye, EyeOff } from 'lucide-react'
import { type ComponentProps, type ReactNode, useId, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface FieldProps extends ComponentProps<typeof Input> {
  label: string
  error?: string
  hint?: ReactNode
  labelAside?: ReactNode
}

/** Label + input + hint/error, wired with aria attributes for screen readers. */
export function Field({ label, error, hint, labelAside, className, id, ...props }: FieldProps) {
  const autoId = useId()
  const inputId = id ?? autoId
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={inputId}>{label}</Label>
        {labelAside}
      </div>
      <Input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn('h-10', className)}
        {...props}
      />
      {error ? (
        <p id={`${inputId}-error`} role="alert" className="text-destructive text-[0.8rem]">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-muted-foreground text-[0.8rem]">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export function PasswordField(props: Omit<FieldProps, 'type'>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Field {...props} type={visible ? 'text' : 'password'} className="pr-10" />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className="text-muted-foreground hover:text-foreground absolute top-[1.85rem] right-1 grid size-8 place-items-center rounded-md"
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

export function FormAlert({ children, tone = 'error' }: { children: ReactNode; tone?: 'error' | 'success' }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn(
        'rounded-md border px-3 py-2 text-sm',
        tone === 'error'
          ? 'border-destructive/30 bg-destructive/5 text-destructive'
          : 'border-success/30 bg-success/5 text-success',
      )}
    >
      {children}
    </div>
  )
}
