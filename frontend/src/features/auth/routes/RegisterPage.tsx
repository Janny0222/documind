import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { Field, FormAlert, PasswordField } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import { useRegister } from '@/features/auth/api'
import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { safeNext } from '@/lib/format'
import { type RegisterValues, registerSchema } from '@/features/auth/schemas'
import { applyServerErrors } from '@/lib/form-errors'

export function RegisterPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const registerUser = useRegister()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { display_name: '', email: '', password: '' },
  })
  const { errors } = formState

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null)
    try {
      await registerUser.mutateAsync(values)
      navigate(safeNext(params.get('next')), { replace: true })
    } catch (err) {
      const message = applyServerErrors(err, setError, ['display_name', 'email', 'password'])
      if (message && /already exists/i.test(message)) {
        setError('email', { type: 'server', message: 'An account with this email already exists.' })
      } else {
        setFormError(message)
      }
    }
  })

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle="Upload documents and ask them questions. Free while in beta."
      footer={
        <>
          Already have an account?{' '}
          <Link to={{ pathname: '/login', search: params.toString() }} className="text-primary font-medium hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="grid gap-5">
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <Field
          label="Your name"
          autoComplete="name"
          autoFocus
          error={errors.display_name?.message}
          {...register('display_name')}
        />
        <Field label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register('email')} />
        <PasswordField
          label="Password"
          autoComplete="new-password"
          hint="At least 10 characters. A short phrase works well."
          error={errors.password?.message}
          {...register('password')}
        />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Create account
        </Button>
        <p className="text-muted-foreground text-[0.8rem] leading-relaxed">
          Documents you index are processed by Google Gemini. Don&apos;t upload confidential files to
          the public demo.
        </p>
      </form>
    </AuthLayout>
  )
}
