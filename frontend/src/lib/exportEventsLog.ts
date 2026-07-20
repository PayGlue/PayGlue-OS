// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
import type { WebhookEvent } from '../types/api'

const SECRET_KEY_PATTERN = /token|secret|password|api[-_]?key|authorization|credential/i

/** Recursively redacts secret-looking values and masks email addresses in a payload. */
export function redactPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactPayload)
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      if (SECRET_KEY_PATTERN.test(key)) {
        out[key] = '[redacted]'
      } else if (typeof val === 'string' && /email/i.test(key)) {
        out[key] = maskEmail(val)
      } else {
        out[key] = redactPayload(val)
      }
    }
    return out
  }
  return value
}

function maskEmail(email: string): string {
  const at = email.indexOf('@')
  if (at <= 0) return email
  const local = email.slice(0, at)
  const domain = email.slice(at)
  const visible = local.slice(0, Math.min(2, local.length))
  return `${visible}${'*'.repeat(Math.max(local.length - visible.length, 1))}${domain}`
}

export function buildEventsLogMarkdown(events: WebhookEvent[], context: { tenantSlug: string; filterSummary: string }): string {
  const now = new Date().toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
  const lines = [
    `# Webhook event log for ${context.tenantSlug}`,
    `Exported ${now} · ${events.length} event${events.length === 1 ? '' : 's'}${context.filterSummary ? ` · ${context.filterSummary}` : ''}`,
    '',
  ]

  for (const event of events) {
    const received = new Date(event.created_at).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
    lines.push(`## Event ${event.id} · ${event.provider} · ${event.status}`)
    lines.push(`- Received: ${received}`)
    lines.push(`- Attempts: ${event.attempts}`)
    if (event.last_error) lines.push(`- Error: ${event.last_error}`)
    lines.push('')
    lines.push('```json')
    lines.push(JSON.stringify(redactPayload(event.payload_snapshot), null, 2))
    lines.push('```')
    lines.push('')
  }

  return lines.join('\n')
}
