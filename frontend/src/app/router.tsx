import type { ComponentType } from 'react'
import { createBrowserRouter, Outlet, type RouteObject } from 'react-router'
import { RouteError } from '@/app/RouteError'
import { FullPageLoader, GuestOnly, RequireAuth } from '@/features/auth/guards'
import { LoginPage } from '@/features/auth/routes/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from '@/features/auth/routes/PasswordRecovery'
import { RegisterPage } from '@/features/auth/routes/RegisterPage'
import { WorkspaceGate, WorkspaceHome } from '@/features/workspaces/context'
import { InvitePage } from '@/features/workspaces/InvitePage'

// In-app pages are code-split: the sign-in screen never downloads the app shell, and each
// page loads on first visit. React Router's lazy() resolves before rendering (no spinners).
const page = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) => async () => ({
  Component: (await load())[name],
})

export const routes: RouteObject[] = [
  {
    element: <Outlet />,
    errorElement: <RouteError />,
    // Shown while the first (lazy) page chunk loads on a cold start.
    hydrateFallbackElement: <FullPageLoader />,
    children: [
      // Signed-out only
      {
        element: <GuestOnly />,
        children: [
          { path: 'login', element: <LoginPage /> },
          { path: 'register', element: <RegisterPage /> },
        ],
      },
      // Token links from emails: work signed in or out
      { path: 'forgot-password', element: <ForgotPasswordPage /> },
      { path: 'reset-password', element: <ResetPasswordPage /> },
      { path: 'verify-email', element: <VerifyEmailPage /> },
      { path: 'invite', element: <InvitePage /> },
      // The app
      {
        element: <RequireAuth />,
        children: [
          { index: true, element: <WorkspaceHome /> },
          {
            path: 'w/:workspaceId',
            lazy: async () => {
              const { AppShell } = await import('@/layouts/AppShell')
              return {
                Component: () => (
                  <WorkspaceGate>
                    <AppShell />
                  </WorkspaceGate>
                ),
              }
            },
            children: [
              { index: true, lazy: page(() => import('@/features/dashboard/DashboardPage'), 'DashboardPage') },
              { path: 'documents', lazy: page(() => import('@/features/documents/DocumentsPage'), 'DocumentsPage') },
              { path: 'collections', lazy: page(() => import('@/features/documents/CollectionsPage'), 'CollectionsPage') },
              {
                path: 'collections/:collectionId',
                lazy: page(() => import('@/features/documents/CollectionsPage'), 'CollectionDetailPage'),
              },
              // One route with an optional id: a new chat keeps streaming when its URL gains the id.
              { path: 'search', lazy: page(() => import('@/features/insights/SearchPage'), 'SearchPage') },
              { path: 'analytics', lazy: page(() => import('@/features/insights/AnalyticsPage'), 'AnalyticsPage') },
              { path: 'ask/:conversationId?', lazy: page(() => import('@/features/ai/AskPage'), 'AskPage') },
              {
                path: 'settings',
                lazy: page(() => import('@/features/settings/SettingsLayout'), 'SettingsLayout'),
                children: [
                  { index: true, lazy: page(() => import('@/features/settings/WorkspaceSettings'), 'WorkspaceSettings') },
                  { path: 'members', lazy: page(() => import('@/features/settings/MembersSettings'), 'MembersSettings') },
                  { path: 'account', lazy: page(() => import('@/features/settings/AccountSettings'), 'AccountSettings') },
                  { path: 'activity', lazy: page(() => import('@/features/settings/ActivitySettings'), 'ActivitySettings') },
                ],
              },
            ],
          },
        ],
      },
      { path: '*', element: <RouteError /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
