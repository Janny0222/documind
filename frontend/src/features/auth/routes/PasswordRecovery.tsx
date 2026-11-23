import { zodResolver } from '@hookform/resolvers/zod'
import { CheckCircle2, Loader2, MailCheck, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { Field, FormAlert, PasswordField } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import { useForgotPassword, useResetPassword, useVerifyEmail } from '@/features/auth/api'
import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { type ForgotValues, forgotSchema, type ResetValues, resetSchema } from '@/features/auth/schemas'
import { applyServerErrors, takeHashToken } from '@/lib/form-errors'

const backToSignIn = (
  <Link to="/login" className="text-primary font-medium hover:underline">
    Back to sign in
  </Link>
)

export function ForgotPasswordPage() {
  const forgot = useForgotPassword()
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState } = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })

  const onSubmit = handleSubmit(async ({ email }) => {
    setFormError(null)
    try {
      await forgot.mutateAsync(email)
      setSentTo(email)
    } catch (err) {
      setFormError(applyServerErrors(err, setError, ['email']))
    }
  })

  if (sentTo) {
    return (
      <AuthLayout title="Check your inbox" footer={backToSignIn}>
        <div className="flex gap-3">
          <MailCheck className="text-primary mt-0.5 size-5 shrink-0" aria-hidden />
          <p className="text-muted-foreground">
            If an account exists for <span className="text-foreground font-medium">{sentTo}</span>,
            we sent a link to reset your password. It expires in 60 minutes.
          </p>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your account email and we'll send you a reset link."
      footer={backToSignIn}
    >
      <form onSubmit={onSubmit} noValidate className="grid gap-5">
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          error={formState.errors.email?.message}
          {...register('email')}
        />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  )
}

export function ResetPasswordPage() {
  const [token] = useState(takeHashToken)
  const reset = useResetPassword()
  const [done, setDone] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { new_password: '', confirm: '' },
  })

  const onSubmit = handleSubmit(async ({ new_password }) => {
    if (!token) return
    setFormError(null)
    try {
      await reset.mutateAsync({ token, new_password })
      setDone(true)
    } catch (err) {
      setFormError(
        applyServerErrors(err, setError, ['new_password'], {
          invalid_token: 'This reset link is invalid or has expired. Request a new one.',
        }),
      )
    }
  })

  if (!token) {
    return (
      <AuthLayout title="This link is incomplete" footer={backToSignIn}>
        <p className="text-muted-foreground">
          Open the reset link from your email again, or{' '}
          <Link to="/forgot-password" className="text-primary font-medium hover:underline">
            request a new one
          </Link>
          .
        </p>
      </AuthLayout>
    )
  }

  if (done) {
    return (
      <AuthLayout title="Password updated" footer={backToSignIn}>
        <p className="text-muted-foreground">
          You&apos;ve been signed out on all devices. Sign in with your new password.
        </p>
        <Button asChild size="lg" className="mt-6 w-full">
          <Link to="/login">Sign in</Link>
        </Button>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Choose a new password" footer={backToSignIn}>
      <form onSubmit={onSubmit} noValidate className="grid gap-5">
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <PasswordField
          label="New password"
          autoComplete="new-password"
          autoFocus
          hint="At least 10 characters."
          error={formState.errors.new_password?.message}
          {...register('new_password')}
        />
        <PasswordField
          label="Confirm new password"
          autoComplete="new-password"
          error={formState.errors.confirm?.message}
          {...register('confirm')}
        />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Update password
        </Button>
      </form>
    </AuthLayout>
  )
}

export function VerifyEmailPage() {
  const [token] = useState(takeHashToken)
  const verify = useVerifyEmail()
  const started = useRef(false)

  useEffect(() => {
    // Run once (StrictMode mounts effects twice in dev; the token is single-use).
    if (token && !started.current) {
      started.current = true
      verify.mutate(token)
    }
  }, [token, verify])

  const continueLink = (
    <Link to="/" className="text-primary font-medium hover:underline">
      Continue to DocuMind
    </Link>
  )

  if (!token || verify.isError) {
    return (
      <AuthLayout title="We couldn't verify your email" footer={continueLink}>
        <div className="flex gap-3">
          <XCircle className="text-destructive mt-0.5 size-5 shrink-0" aria-hidden />
          <p className="text-muted-foreground">
            The link is invalid or has expired. Sign in and request a new link from your account
            settings.
          </p>
        </div>
      </AuthLayout>
    )
  }

  if (verify.isSuccess) {
    return (
      <AuthLayout title="Email verified" footer={continueLink}>
        <div className="flex gap-3">
          <CheckCircle2 className="text-success mt-0.5 size-5 shrink-0" aria-hidden />
          <p className="text-muted-foreground">Thanks - your email address is confirmed.</p>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Verifying your email">
      <p className="text-muted-foreground flex items-center gap-2">
        <Loader2 className="size-4 animate-spin" aria-hidden /> One moment…
      </p>
    </AuthLayout>
  )
}
