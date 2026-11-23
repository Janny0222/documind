/**
 * Cloudflare Pages Function: same-origin reverse proxy  /api/*  ->  FastAPI on Render.
 *
 * Why: the SPA (pages.dev) and API (onrender.com) are different sites. Browsers increasingly
 * block third-party cookies, which would break HttpOnly cookie auth. Proxying through the
 * Pages origin makes every API cookie first-party. See docs/PHASE-1-ARCHITECTURE.md §C.
 *
 * Configure in Cloudflare Pages → Settings → Variables:
 *   API_ORIGIN   = https://<service>.onrender.com
 *   PROXY_SECRET = same value as PROXY_SHARED_SECRET on Render (encrypt it). The API refuses
 *                  /api/* requests without it, so nobody can go around this proxy.
 * Streams request and response bodies, so uploads and SSE answers pass straight through.
 *
 * Verified locally with `pnpm preview:pages` (wrangler) against the production API image.
 */

interface Env {
  API_ORIGIN: string
  PROXY_SECRET?: string
}

interface PagesContext {
  request: Request
  env: Env
}

// Hop-by-hop headers must not be forwarded (RFC 9110 §7.6.1).
const HOP_BY_HOP = ['connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'proxy-connection', 'te', 'trailer']

export const onRequest = async ({ request, env }: PagesContext): Promise<Response> => {
  if (!env.API_ORIGIN) {
    return Response.json(
      { status: 503, code: 'proxy_misconfigured', title: 'API unavailable', detail: 'API_ORIGIN is not set' },
      { status: 503, headers: { 'Content-Type': 'application/problem+json' } },
    )
  }

  const incoming = new URL(request.url)
  const target = new URL(incoming.pathname + incoming.search, env.API_ORIGIN)

  const headers = new Headers(request.headers)
  for (const h of HOP_BY_HOP) headers.delete(h)
  headers.delete('host')
  headers.set('X-Forwarded-Host', incoming.host)
  headers.set('X-Forwarded-Proto', incoming.protocol.replace(':', ''))
  const clientIp = request.headers.get('CF-Connecting-IP')
  if (clientIp) headers.set('X-Forwarded-For', clientIp)
  // Always overwrite: a client-sent X-Proxy-Secret must never pass through.
  headers.delete('X-Proxy-Secret')
  if (env.PROXY_SECRET) headers.set('X-Proxy-Secret', env.PROXY_SECRET)

  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      redirect: 'manual',
    })
  } catch {
    // Render's free tier sleeps when idle; the SPA shows a "waking up" state for this.
    return Response.json(
      { status: 503, code: 'api_unreachable', title: 'API unavailable', detail: 'The API is starting up. Try again in a moment.' },
      { status: 503, headers: { 'Content-Type': 'application/problem+json', 'Retry-After': '15' } },
    )
  }

  const responseHeaders = new Headers(upstream.headers)
  for (const h of HOP_BY_HOP) responseHeaders.delete(h)
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders })
}
