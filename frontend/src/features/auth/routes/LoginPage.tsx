import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { Field, FormAlert, PasswordField } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import { useLogin } from '@/features/auth/api'
import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { type LoginValues, loginSchema } from '@/features/auth/schemas'
import { applyServerErrors } from '@/lib/form-errors'
import { safeNext } from '@/lib/format'

export function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const login = useLogin()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })
  const { errors } = formState
  const sessionEnded = params.get('reason') === 'session_ended'

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null)
    try {
      await login.mutateAsync(values)
      navigate(safeNext(params.get('next')), { replace: true })
    } catch (err) {
      setFormError(
        applyServerErrors(err, setError, ['email', 'password'], {
          invalid_credentials: 'That email and password combination is incorrect.',
          email_not_verified: 'Verify your email address first - check your inbox for the link.',
        }),
      )
    }
  })

  return (
    <AuthLayout
      title="Sign in to DocuMind"
      subtitle="Pick up where you left off."
      footer={
        <>
          New to DocuMind?{' '}
          <Link to={{ pathname: '/register', search: params.toString() }} className="text-primary font-medium hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="grid gap-5">
        {sessionEnded && !formError ? (
          <FormAlert tone="success">Your session ended. Sign in again to continue.</FormAlert>
        ) : null}
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          error={errors.email?.message}
          {...register('email')}
        />
        <PasswordField
          label="Password"
          autoComplete="current-password"
          error={errors.password?.message}
          labelAside={
            <Link to="/forgot-password" className="text-primary text-[0.8rem] font-medium hover:underline">
              Forgot password?
            </Link>
          }
          {...register('password')}
        />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Sign in
        </Button>
      </form>
    </AuthLayout>
  )
}
