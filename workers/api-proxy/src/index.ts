// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

interface Env {
  SUPABASE_PROJECT_REF: string
  RAILWAY_BACKEND_URL: string
  WEBHOOK_ENDPOINT_TOKEN: string
}

const SUPABASE_ROUTES: Record<string, string> = {
  '/contact': '/functions/v1/send-contact',
  '/withdrawal': '/functions/v1/send-withdrawal',
}

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Authorization, Content-Type',
  'Access-Control-Max-Age': '86400',
}

function addCors(response: Response): Response {
  const headers = new Headers(response.headers)
  Object.entries(CORS_HEADERS).forEach(([k, v]) => headers.set(k, v))
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)
    const path = url.pathname

    // Handle CORS preflight for all routes
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS })
    }

    // Route Polar webhooks to Django: /webhooks/polar?tenant={slug} → /t/{slug}/webhooks/polar/{token}/
    if (path === '/webhooks/polar') {
      const tenantSlug = url.searchParams.get('tenant')
      if (!tenantSlug) return new Response('Missing tenant parameter', { status: 400, headers: CORS_HEADERS })
      const token = env.WEBHOOK_ENDPOINT_TOKEN
      const djangoPath = `/t/${tenantSlug}/webhooks/polar/${token}/`
      const target = new URL(env.RAILWAY_BACKEND_URL + djangoPath)
      const res = await fetch(new Request(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
      }))
      console.log(`[webhook] polar tenant=${tenantSlug} → ${res.status}`)
      return addCors(res)
    }

    // Route Lemon Squeezy webhooks to Django: /webhooks/lemonsqueezy?tenant={slug} → /t/{slug}/webhooks/lemonsqueezy/{token}/
    if (path === '/webhooks/lemonsqueezy') {
      const tenantSlug = url.searchParams.get('tenant')
      if (!tenantSlug) return new Response('Missing tenant parameter', { status: 400, headers: CORS_HEADERS })
      const token = env.WEBHOOK_ENDPOINT_TOKEN
      const djangoPath = `/t/${tenantSlug}/webhooks/lemonsqueezy/${token}/`
      const target = new URL(env.RAILWAY_BACKEND_URL + djangoPath)
      const res = await fetch(new Request(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
      }))
      console.log(`[webhook] lemonsqueezy tenant=${tenantSlug} → ${res.status}`)
      return addCors(res)
    }

    // Route PayPal webhooks to Django: /webhooks/paypal?tenant={slug} → /t/{slug}/webhooks/paypal/{token}/
    if (path === '/webhooks/paypal') {
      const tenantSlug = url.searchParams.get('tenant')
      if (!tenantSlug) return new Response('Missing tenant parameter', { status: 400, headers: CORS_HEADERS })
      const token = env.WEBHOOK_ENDPOINT_TOKEN
      const djangoPath = `/t/${tenantSlug}/webhooks/paypal/${token}/`
      const target = new URL(env.RAILWAY_BACKEND_URL + djangoPath)
      const res = await fetch(new Request(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
      }))
      console.log(`[webhook] paypal tenant=${tenantSlug} → ${res.status}`)
      return addCors(res)
    }

    const supabaseFn = SUPABASE_ROUTES[path]
    if (supabaseFn) {
      const target = new URL(`https://${env.SUPABASE_PROJECT_REF}.supabase.co${supabaseFn}`)
      target.search = url.search
      const res = await fetch(new Request(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
      }))
      return addCors(res)
    }

    if (
      path.startsWith('/t/') ||
      path.startsWith('/api/') ||
      path === '/paywall.js' ||
      path === '/button.js' ||
      path === '/pricing-table.js'
    ) {
      const target = new URL(env.RAILWAY_BACKEND_URL + path)
      target.search = url.search
      const res = await fetch(new Request(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
      }))
      console.log(`[proxy] ${request.method} ${path} → ${res.status}`)
      return addCors(res)
    }

    return new Response('Not found', { status: 404, headers: CORS_HEADERS })
  },
}
