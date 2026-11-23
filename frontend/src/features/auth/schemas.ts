import { z } from 'zod'

// Mirrors backend/app/schemas/auth.py so most mistakes are caught before a round trip.
const email = z.email('Enter a valid email address').max(254)
const newPassword = z
  .string()
  .min(10, 'Use at least 10 characters')
  .max(128, 'Use at most 128 characters')

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Enter your password'),
})
export type LoginValues = z.infer<typeof loginSchema>

export const registerSchema = z.object({
  display_name: z.string().trim().min(1, 'Enter your name').max(80),
  email,
  password: newPassword,
})
export type RegisterValues = z.infer<typeof registerSchema>

export const forgotSchema = z.object({ email })
export type ForgotValues = z.infer<typeof forgotSchema>

export const resetSchema = z
  .object({ new_password: newPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, {
    path: ['confirm'],
    message: "Passwords don't match",
  })
export type ResetValues = z.infer<typeof resetSchema>

export const changePasswordSchema = z
  .object({ current_password: z.string().min(1, 'Enter your current password'), new_password: newPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, {
    path: ['confirm'],
    message: "Passwords don't match",
  })
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>
