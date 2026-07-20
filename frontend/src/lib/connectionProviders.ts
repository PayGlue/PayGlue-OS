// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// The connection registry: everything the generic ConnectionDetailView needs
// to render and save each payment provider WITHOUT losing field parity. The
// credential `key`s here MUST match exactly what the old per-provider views
// sent to setIntegrationCredentials -- otherwise a saved connection breaks.
//
// Ghost (cms) and Stripe are NOT here: Ghost keeps its own detail view, and
// Stripe is a read-only status view (no credential form).

import { PROVIDER_BRAND } from './providers'

export type ProviderKey =
  | 'polar'
  | 'lemonsqueezy'
  | 'paypal'
  | 'gumroad'
  | 'paddle'
  | 'kofi'
  | 'creem'
  | 'patreon'

export interface CredField {
  /** Credential key POSTed to setIntegrationCredentials -- do not change. */
  key: string
  label: string
  placeholder: string
  /** Plaintext by default is a password field; a few IDs are plain text. */
  inputType?: 'password' | 'text'
  /** Optional field never blocks enabling and shows an "(optional)" marker. */
  optional?: boolean
  hint?: string
  /**
   * How we decide the field already holds a saved secret (to show dots):
   *  - 'enabled'        → stored once the integration is enabled (the webhook/
   *                       signing secret, which older views gated on `enabled`)
   *  - 'credential_ref' → stored when metadata.credential_ref.masked_keys lists it
   *  - 'polar_token'    → stored when Polar's product endpoint reports has_token
   */
  detect?: 'enabled' | 'credential_ref' | 'polar_token'
}

export interface SetupStep {
  title: string
  /** May contain <strong>/<code>; rendered via v-html (trusted static copy). */
  bodyHtml: string
  /** Optional monospace event list under the body. */
  events?: string[]
}

export interface ConnectionProvider {
  key: ProviderKey
  name: string
  blurb: string
  docsUrl: string
  /** Shown next to the red dot when not yet connected. */
  notConnectedMsg: string
  /** Field key that must be present on the first save (hard-validated). */
  requireOnFirstSave?: string
  fields: CredField[]
  /** Credentials always merged on save (e.g. PayPal's sandbox flag). */
  staticCreds?: Record<string, string>
  /** Credentials derived from the entered values (e.g. Paddle sandbox prefix). */
  computeCreds?: (form: Record<string, string>) => Record<string, string>
  /** Lemon Squeezy: show the store selector + send store_id. */
  hasStore?: boolean
  /** Polar: publication-rename webhook warning banner. */
  renameBanner?: boolean
  steps: SetupStep[]
}

const WEBHOOK_HINT = 'Already had a webhook URL configured before? No need to update it, the old URL keeps working.'

export const CONNECTION_PROVIDERS: Record<ProviderKey, ConnectionProvider> = {
  polar: {
    key: 'polar',
    name: PROVIDER_BRAND.polar.name,
    blurb: 'Connect Polar webhooks to automatically sync member access on payment events.',
    docsUrl: 'https://docs.payglue.io/setup/polar',
    notConnectedMsg: 'Not connected. A webhook secret is required',
    requireOnFirstSave: 'webhook_secret',
    renameBanner: true,
    fields: [
      { key: 'webhook_secret', label: 'Webhook secret', placeholder: 'whsec_...', detect: 'enabled' },
      {
        key: 'access_token',
        label: 'Polar API token',
        placeholder: 'polar_at_...',
        optional: true,
        detect: 'polar_token',
        hint: 'Needed for product auto-fetch in Mappings. Get it in Polar under Settings > Preferences > Developers > Access Tokens. Set expiration to Never and enable products:read, checkout_links:read, and checkout_links:write. Without this token you can still add mappings by entering the product ID manually.',
      },
    ],
    steps: [
      { title: 'Open Polar settings', bodyHtml: 'In your Polar dashboard, go to <strong>Settings</strong> and click <strong>Webhooks</strong> in the sidebar.' },
      {
        title: 'Add endpoint',
        bodyHtml: "Click <strong>+ Add endpoint</strong>. Set format to <strong>Raw</strong>, paste the Webhook URL above. Select only these events (we don't recommend \"All events\"):",
        events: ['benefit_grant.created', 'benefit_grant.updated', 'benefit_grant.revoked', 'order.created', 'subscription.active', 'subscription.canceled', 'subscription.revoked'],
      },
      { title: 'Copy the secret', bodyHtml: 'After saving, Polar shows a <strong>Webhook secret</strong>. Copy it, paste it into the field on the left, then click <strong>Save credentials</strong>.' },
    ],
  },

  lemonsqueezy: {
    key: 'lemonsqueezy',
    name: PROVIDER_BRAND.lemonsqueezy.name,
    blurb: 'Connect Lemon Squeezy webhooks to automatically sync member access on payment events.',
    docsUrl: 'https://docs.payglue.io/setup/lemon-squeezy',
    notConnectedMsg: 'Not connected. A signing secret is required',
    requireOnFirstSave: 'webhook_secret',
    hasStore: true,
    fields: [
      {
        key: 'webhook_secret',
        label: 'Signing secret',
        placeholder: 'Your signing secret (same value as entered in Lemon Squeezy)',
        detect: 'enabled',
        hint: 'You choose this secret yourself. Enter the same value here and in Lemon Squeezy.',
      },
      {
        key: 'api_key',
        label: 'API key',
        placeholder: 'Your Lemon Squeezy API key (for product fetching)',
        detect: 'credential_ref',
        hint: 'Used to load your products in the Paywall, Buy Button, and Pricing Table editors. Find it in Lemon Squeezy under Settings > API. To see test products, use the API key generated while test mode is active in the LS dashboard.',
      },
    ],
    steps: [
      { title: 'Open Lemon Squeezy settings', bodyHtml: 'In your Lemon Squeezy dashboard, click your store name and go to <strong>Settings</strong>.' },
      { title: 'Open Webhooks', bodyHtml: 'Click <strong>Webhooks</strong> in the left sidebar, then click <strong>+ Add webhook</strong>.' },
      { title: 'Create a signing secret', bodyHtml: 'In the <strong>Signing secret</strong> field in Lemon Squeezy, enter any random string you choose, for example a long password. You will paste the same value into PayGlue in Step 5.' },
      {
        title: 'Paste the webhook URL and select events',
        bodyHtml: 'Paste the Webhook URL from the left into <strong>Callback URL</strong>. Then enable these events:',
        events: ['order_created', 'subscription_created', 'subscription_updated', 'subscription_resumed', 'subscription_unpaused', 'subscription_payment_success', 'subscription_cancelled', 'subscription_paused', 'subscription_expired'],
      },
      { title: 'Save in PayGlue', bodyHtml: 'Enter the <strong>same signing secret</strong> you chose in Step 3 into the field on the left, then click <strong>Save credentials</strong>.' },
    ],
  },

  paypal: {
    key: 'paypal',
    name: PROVIDER_BRAND.paypal.name,
    blurb: 'Connect PayPal webhooks to automatically sync member access on subscription and payment events.',
    docsUrl: 'https://docs.payglue.io/setup/paypal',
    notConnectedMsg: 'Not connected. Client ID and Secret are required',
    staticCreds: { sandbox: 'false' },
    fields: [
      { key: 'client_id', label: 'Client ID', placeholder: 'Your PayPal REST API Client ID' },
      { key: 'client_secret', label: 'Client Secret', placeholder: 'Your PayPal REST API Client Secret' },
      { key: 'webhook_id', label: 'Webhook ID', placeholder: 'Webhook ID from PayPal Developer dashboard', inputType: 'text', hint: 'PayPal uses this to verify webhook authenticity. You find it after creating the webhook in the Developer dashboard.' },
    ],
    steps: [
      { title: 'Open the PayPal Developer dashboard', bodyHtml: 'Go to <strong>developer.paypal.com</strong>, log in with your PayPal business account, and open <strong>Apps &amp; Credentials</strong>.' },
      { title: 'Create a REST API app', bodyHtml: 'Click <strong>Create App</strong>, give it a name (e.g. "PayGlue"), and select <strong>Merchant</strong> as the app type. After creation, copy the <strong>Client ID</strong> and <strong>Client Secret</strong>.' },
      {
        title: 'Add a webhook',
        bodyHtml: 'Scroll down to <strong>Webhooks</strong> inside your app and click <strong>Add Webhook</strong>. Paste the Webhook URL from the left. Enable these events:',
        events: ['BILLING.SUBSCRIPTION.ACTIVATED', 'BILLING.SUBSCRIPTION.CANCELLED', 'BILLING.SUBSCRIPTION.EXPIRED', 'BILLING.SUBSCRIPTION.SUSPENDED', 'BILLING.SUBSCRIPTION.UPDATED', 'PAYMENT.CAPTURE.COMPLETED'],
      },
      { title: 'Copy the Webhook ID', bodyHtml: 'After saving the webhook, PayPal shows a <strong>Webhook ID</strong>. Copy it and paste it into the field on the left.' },
      { title: 'Save in PayGlue', bodyHtml: 'Enter Client ID, Client Secret, and Webhook ID into the fields on the left, then click <strong>Save credentials</strong>.' },
    ],
  },

  gumroad: {
    key: 'gumroad',
    name: PROVIDER_BRAND.gumroad.name,
    blurb: 'Connect Gumroad webhooks to automatically sync member access on sale and subscription events.',
    docsUrl: 'https://docs.payglue.io/setup/gumroad',
    notConnectedMsg: 'Not connected. Application Secret and Access Token are required',
    fields: [
      { key: 'application_id', label: 'Application ID', placeholder: 'Your Gumroad Application ID' },
      { key: 'application_secret', label: 'Application Secret', placeholder: 'Your Gumroad Application Secret', hint: 'Also used to verify that incoming webhooks really come from Gumroad.' },
      { key: 'access_token', label: 'Access Token', placeholder: 'Access token for your own account', hint: 'Generated for your own Gumroad account after creating the application, with no review by Gumroad required.' },
    ],
    steps: [
      { title: 'Create your own application', bodyHtml: 'In your Gumroad account, go to <strong>Settings → Advanced → Applications</strong> and click <strong>Create Application</strong>. This runs entirely in your own account, so Gumroad does not need to review or approve it.' },
      { title: 'Copy Application ID and Secret', bodyHtml: 'After creating the application, copy its <strong>Application ID</strong> and <strong>Application Secret</strong> into the fields on the left.' },
      { title: 'Generate an access token', bodyHtml: 'Next to your new application, generate an access token for your own account and paste it into <strong>Access Token</strong> on the left. PayGlue uses this to read sale data.' },
      { title: 'Save in PayGlue', bodyHtml: 'Enter Application ID, Application Secret, and Access Token into the fields on the left, then click <strong>Save credentials</strong>. PayGlue registers the <code>sale</code>, <code>cancellation</code>, and <code>subscription_ended</code> webhook events with Gumroad for you automatically, so no extra setup in Gumroad is needed.' },
    ],
  },

  paddle: {
    key: 'paddle',
    name: PROVIDER_BRAND.paddle.name,
    blurb: 'Connect Paddle webhooks to automatically sync member access on transaction and subscription events.',
    docsUrl: 'https://docs.payglue.io/setup/paddle',
    notConnectedMsg: 'Not connected. API Key and Webhook Secret are required',
    // Sandbox vs live is detected from the API key prefix, matching the old view.
    computeCreds: (form) => ({ sandbox: (form.api_key ?? '').startsWith('pdl_sdbx_') ? 'true' : 'false' }),
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'pdl_live_apikey_... or pdl_sdbx_apikey_...', hint: 'Sandbox vs. live is detected automatically from the key prefix.' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'pdl_ntfset_...', hint: 'Used to verify that incoming webhooks really come from Paddle.' },
    ],
    steps: [
      { title: 'Create an API key', bodyHtml: 'In Paddle, go to <strong>Developer tools → Authentication</strong> and create a new API key. Copy it immediately, because Paddle only shows it once.' },
      {
        title: 'Add a notification destination',
        bodyHtml: 'Go to <strong>Developer tools → Notifications</strong>, click <strong>+ New destination</strong>, paste the Webhook URL above, and select these events:',
        events: ['transaction.completed', 'subscription.activated', 'subscription.resumed', 'subscription.canceled', 'subscription.paused', 'subscription.past_due'],
      },
      { title: 'Copy the secret key', bodyHtml: 'After saving the destination, open it and copy its <strong>secret key</strong> into the field on the left.' },
      { title: 'Save in PayGlue', bodyHtml: 'Enter the API Key and Webhook Secret into the fields on the left, then click <strong>Save credentials</strong>.' },
    ],
  },

  kofi: {
    key: 'kofi',
    name: PROVIDER_BRAND.kofi.name,
    blurb: 'Connect Ko-fi webhooks to automatically sync member access on donations and memberships.',
    docsUrl: 'https://docs.payglue.io/setup/kofi',
    notConnectedMsg: 'Not connected. A verification token is required',
    fields: [
      { key: 'verification_token', label: 'Verification Token', placeholder: 'Your Ko-fi Verification Token', hint: 'Used to verify that incoming webhooks really come from Ko-fi.' },
    ],
    steps: [
      { title: "Open Ko-fi's Webhooks settings", bodyHtml: 'In your Ko-fi account, go to <strong>Settings → Webhooks</strong> (under the API section).' },
      { title: 'Paste the Webhook URL', bodyHtml: 'Copy the <strong>Webhook URL</strong> from the left and paste it into Ko-fi\'s "Webhook URL" field, then save.' },
      { title: 'Copy the Verification Token', bodyHtml: 'Ko-fi shows a <strong>Verification Token</strong> on the same page. Copy it into the field on the left, then click <strong>Save credentials</strong>.' },
    ],
  },

  creem: {
    key: 'creem',
    name: PROVIDER_BRAND.creem.name,
    blurb: 'Connect Creem webhooks to automatically sync member access on checkout and subscription events.',
    docsUrl: 'https://docs.payglue.io/setup/creem',
    notConnectedMsg: 'Not connected. API Key and Webhook Secret are required',
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'creem_...', hint: 'Found under Developers → API Keys in your Creem dashboard.' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'whsec_...', hint: 'Used to verify that incoming webhooks really come from Creem.' },
    ],
    steps: [
      { title: 'Create an API key', bodyHtml: 'In Creem, go to <strong>Developers → API Keys</strong> and create a new key.' },
      { title: 'Add a webhook endpoint', bodyHtml: 'Go to <strong>Developers → Webhooks</strong>, click <strong>Add endpoint</strong>, paste the Webhook URL above, and select checkout and subscription events.' },
      { title: 'Copy the signing secret', bodyHtml: 'After saving the endpoint, copy its <strong>signing secret</strong> into the field on the left.' },
      { title: 'Save in PayGlue', bodyHtml: 'Enter the API Key and Webhook Secret into the fields on the left, then click <strong>Save credentials</strong>. Test-mode keys work automatically, no extra toggle needed.' },
    ],
  },

  patreon: {
    key: 'patreon',
    name: PROVIDER_BRAND.patreon.name,
    blurb: 'Connect Patreon so an active pledge automatically grants your mapped Ghost access, and a cancelled pledge revokes it.',
    docsUrl: 'https://docs.payglue.io/setup/patreon',
    notConnectedMsg: 'Not connected. Access Token and Webhook Secret are required',
    fields: [
      { key: 'access_token', label: "Creator's Access Token", placeholder: "Creator's Access Token", hint: 'Used to load your tier list so you can map tiers to Ghost access. Found in the Patreon developer portal under your client.' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Webhook secret', hint: 'Shown next to your webhook in the Patreon developer portal. Used to verify incoming webhooks really come from Patreon.' },
    ],
    steps: [
      { title: 'Register a client', bodyHtml: 'In the <strong>Patreon developer portal</strong> (patreon.com/portal), create a client for your campaign. Copy the <strong>Creator\'s Access Token</strong> it gives you.' },
      { title: 'Register a webhook', bodyHtml: "In the portal's <strong>Webhooks</strong> section, paste the Webhook URL above and enable the <strong>members:pledge:create</strong>, <strong>members:pledge:update</strong>, and <strong>members:pledge:delete</strong> triggers." },
      { title: 'Copy the webhook secret', bodyHtml: 'Patreon shows a <strong>secret</strong> next to your webhook. Paste it, and the Access Token, into the fields on the left, then click <strong>Save credentials</strong>.' },
      { title: 'Map your tiers', bodyHtml: 'On the <strong>Product mapping</strong> page, pick each Patreon tier and choose which Ghost access it grants. A cancelled pledge automatically revokes all Patreon-granted access.' },
    ],
  },
}

export const WEBHOOK_URL_HINT = WEBHOOK_HINT

/** Display order for the Connections overview grid + provider sub-nav. */
export const PROVIDER_ORDER: ProviderKey[] = [
  'polar',
  'lemonsqueezy',
  'paypal',
  'gumroad',
  'creem',
  'patreon',
  'kofi',
  'paddle',
]

export const isConnectionProvider = (key: string): key is ProviderKey =>
  Object.prototype.hasOwnProperty.call(CONNECTION_PROVIDERS, key)
