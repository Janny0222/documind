import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, MailWarning } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { Field, FormAlert, PasswordField } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import { useChangePassword, useMe, useResendVerification, useUpdateProfile } from '@/features/auth/api'
import { type ChangePasswordValues, changePasswordSchema } from '@/features/auth/schemas'
import { SettingsSection } from '@/features/settings/SettingsLayout'
import { toApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/form-errors'
import type { Theme } from '@/lib/types'
import { cn } from '@/lib/utils'
import { usePreferences } from '@/stores/preferences'

const profileSchema = z.object({ display_name: z.string().trim().min(1, 'Enter your name').max(80) })

export function AccountSettings() {
  const { data: user } = useMe()
  if (!user) return null
  return (
    <div className="grid gap-6">
      {!user.email_verified ? <VerifyBanner email={user.email} /> : null}
      <ProfileForm defaultName={user.display_name} email={user.email} />
      <ThemePicker />
      <PasswordForm />
    </div>
  )
}

function VerifyBanner({ email }: { email: string }) {
  const resend = useResendVerification()
  return (
    <div className="border-warning/30 bg-warning/5 flex flex-wrap items-center gap-3 rounded-xl border p-4">
      <MailWarning className="text-warning size-5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 text-sm">
        Confirm <span className="font-medium">{email}</span> to make sure you can always recover your
        account.
      </p>
      <Button
        size="sm"
        variant="outline"
        disabled={resend.isPending || resend.isSuccess}
        onClick={() =>
          resend.mutate(undefined, {
            onSuccess: () => toast.success('Verification email sent'),
            onError: (e) => toast.error(toApiError(e).message),
          })
        }
      >
        {resend.isSuccess ? 'Email sent' : 'Resend email'}
      </Button>
    </div>
  )
}

function ProfileForm({ defaultName, email }: { defaultName: string; email: string }) {
  const update = useUpdateProfile()
  const { register, handleSubmit, formState, reset } = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: { display_name: defaultName },
  })
  const onSubmit = handleSubmit(async (values) => {
    try {
      const user = await update.mutateAsync(values)
      reset({ display_name: user.display_name })
      toast.success('Profile saved')
    } catch (e) {
      toast.error(toApiError(e).message)
    }
  })
  return (
    <SettingsSection title="Profile" description="How you appear to people in your workspaces.">
      <form onSubmit={onSubmit} noValidate className="grid max-w-md gap-5">
        <Field label="Name" autoComplete="name" error={formState.errors.display_name?.message} {...register('display_name')} />
        <Field label="Email" value={email} readOnly disabled hint="Email changes aren't supported yet." />
        <div>
          <Button type="submit" disabled={!formState.isDirty || formState.isSubmitting}>
            {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Save profile
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}

const themeOptions: { value: Theme; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'Match system' },
]

function ThemePicker() {
  const theme = usePreferences((s) => s.theme)
  const setTheme = usePreferences((s) => s.setTheme)
  const update = useUpdateProfile()
  return (
    <SettingsSection title="Appearance" description="Saved to your account, so it follows you to other devices.">
      <div role="group" aria-label="Theme" className="grid max-w-md grid-cols-3 gap-2">
        {themeOptions.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={theme === o.value}
            onClick={() => {
              setTheme(o.value)
              update.mutate({ theme: o.value })
            }}
            className={cn(
              'rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors',
              theme === o.value ? 'border-primary bg-accent text-accent-foreground' : 'hover:bg-muted',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </SettingsSection>
  )
}

function PasswordForm() {
  const change = useChangePassword()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState, reset } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  })
  const onSubmit = handleSubmit(async ({ current_password, new_password }) => {
    setFormError(null)
    try {
      await change.mutateAsync({ current_password, new_password })
      reset()
      toast.success('Password changed. Other devices were signed out.')
    } catch (err) {
      const message = applyServerErrors(err, setError, ['current_password', 'new_password'], {})
      if (toApiError(err).code === 'invalid_credentials') {
        setError('current_password', { type: 'server', message: 'Current password is incorrect' })
      } else {
        setFormError(message)
      }
    }
  })
  return (
    <SettingsSection title="Password" description="Changing it signs you out everywhere except this device.">
      <form onSubmit={onSubmit} noValidate className="grid max-w-md gap-5">
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <PasswordField label="Current password" autoComplete="current-password" error={formState.errors.current_password?.message} {...register('current_password')} />
        <PasswordField label="New password" autoComplete="new-password" hint="At least 10 characters." error={formState.errors.new_password?.message} {...register('new_password')} />
        <PasswordField label="Confirm new password" autoComplete="new-password" error={formState.errors.confirm?.message} {...register('confirm')} />
        <div>
          <Button type="submit" disabled={formState.isSubmitting}>
            {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Change password
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}
