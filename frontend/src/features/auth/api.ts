import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, http } from '@/lib/api'
import { queryKeys } from '@/lib/query-client'
import type { SessionResponse, Theme, User } from '@/lib/types'
import { usePreferences } from '@/stores/preferences'

/**
 * The current user, or `null` when signed out. A 401 is an answer ("signed out"), not an error,
 * so route guards can redirect without flashing an error state.
 */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async (): Promise<User | null> => {
      try {
        return await http.get<User>('/users/me')
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null
        throw err
      }
    },
    staleTime: 5 * 60_000,
  })
}

function useOnSignedIn() {
  const qc = useQueryClient()
  const setTheme = usePreferences((s) => s.setTheme)
  return (session: SessionResponse) => {
    qc.clear() // never show the previous user's cached data
    qc.setQueryData(queryKeys.me, session.user)
    setTheme(session.user.theme)
  }
}

export interface LoginInput {
  email: string
  password: string
}

export function useLogin() {
  const onSignedIn = useOnSignedIn()
  return useMutation({
    mutationFn: (body: LoginInput) => http.post<SessionResponse>('/auth/login', body),
    onSuccess: onSignedIn,
  })
}

export interface RegisterInput {
  display_name: string
  email: string
  password: string
}

export function useRegister() {
  const onSignedIn = useOnSignedIn()
  return useMutation({
    mutationFn: (body: RegisterInput) => http.post<SessionResponse>('/auth/register', body),
    onSuccess: onSignedIn,
  })
}

export function useLogout() {
  const qc = useQueryClient()
  const setLastWorkspaceId = usePreferences((s) => s.setLastWorkspaceId)
  return useMutation({
    mutationFn: () => http.post<void>('/auth/logout'),
    onSettled: () => {
      setLastWorkspaceId(null)
      qc.clear()
      qc.setQueryData(queryKeys.me, null)
    },
  })
}

export const useForgotPassword = () =>
  useMutation({
    mutationFn: (email: string) => http.post<{ detail: string }>('/auth/forgot-password', { email }),
  })

export const useResetPassword = () =>
  useMutation({
    mutationFn: (body: { token: string; new_password: string }) =>
      http.post<{ detail: string }>('/auth/reset-password', body),
  })

export function useVerifyEmail() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => http.post<{ detail: string }>('/auth/verify-email', { token }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.me }),
  })
}

export const useResendVerification = () =>
  useMutation({ mutationFn: () => http.post<{ detail: string }>('/auth/resend-verification') })

export function useUpdateProfile() {
  const qc = useQueryClient()
  const setTheme = usePreferences((s) => s.setTheme)
  return useMutation({
    mutationFn: (body: { display_name?: string; theme?: Theme }) =>
      http.patch<User>('/users/me', body),
    onSuccess: (user) => {
      qc.setQueryData(queryKeys.me, user)
      setTheme(user.theme)
    },
  })
}

export const useChangePassword = () =>
  useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      http.post<void>('/users/me/password', body),
  })
