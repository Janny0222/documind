# DocuMind Web (React)

Phase 3 frontend: the design system, auth screens, app shell (top nav, workspace switcher, ⌘K command palette, mobile tab bar), dashboard, and workspace/member/account settings. It runs against the real FastAPI backend.

## Run it (PowerShell)
The API and database must be running first (see `backend/README.md`).
```powershell
cd frontend; pnpm install
```
```powershell
pnpm dev
```
Open http://localhost:5173. Vite forwards `/api/*` to `http://localhost:8000`, so auth cookies are same-origin, exactly as in production.

## Scripts
| Command | What it does |
|---|---|
| `pnpm dev` | Dev server with hot reload |
| `pnpm test` | Vitest + Testing Library + MSW (mocked API, no backend needed) |
| `pnpm typecheck` | TypeScript 7 (`tsc -b`) |
| `pnpm lint` | oxlint, including accessibility rules |
| `pnpm build` | Type check and production build into `dist/` |
| `pnpm preview:pages` | Serve `dist/` with the real Cloudflare Pages runtime (wrangler), proxying `/api` to `localhost:8000` |

## How it's put together
| Path | Responsibility |
|---|---|
| `src/lib/api.ts` | The one HTTP client: CSRF header, single-flight session refresh, problem+json → `ApiError` |
| `src/lib/query-client.ts` | TanStack Query defaults and query keys (server state lives here only) |
| `src/stores/` | Zustand, for UI state only: theme, last workspace, command palette. No tokens, ever |
| `src/app/router.tsx` | React Router 8 data router; in-app pages are lazy-loaded chunks |
| `src/features/*` | Feature folders (`api.ts` hooks + components + routes) |
| `src/layouts/` | App shell, command palette, user menu |
| `src/components/ui/` | shadcn/ui (Radix) components |
| `src/index.css` | Design tokens: "Calm intelligence" palette, light and dark, AI gradient utilities |
| `functions/api/[[path]].ts` | Cloudflare Pages Function: production `/api` proxy to Render |

## Security notes
- Auth tokens live only in HttpOnly cookies that JavaScript can't read. `localStorage` holds just the theme and the last workspace id.
- Email links carry tokens in the URL **fragment** (`#token=`), which browsers never send to servers. The app removes the fragment from the address bar after reading it.
- Post-login redirects only accept same-app paths (`safeNext`), which blocks open redirects.
- Route guards only decide what to render. The API authorizes every request itself.
