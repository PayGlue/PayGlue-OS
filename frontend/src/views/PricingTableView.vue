// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, ProviderPicker, UiButton } from '../components/ui'
import UpgradeBanner from '../components/UpgradeBanner.vue'
import PricingTablePreview from '../components/PricingTablePreview.vue'
import { useSessionStore } from '../stores/session'
import { usePageResetStore } from '../stores/pageReset'
import { isPlanLimitError, planKeyFromError } from '../lib/planUpgrade'
import {
  listPricingTables,
  createPricingTable,
  updatePricingTable,
  deletePricingTable,
  getPolarProducts,
  getLemonSqueezyProducts,
  getPayPalProducts,
  getGumroadProducts,
  getPaddleProducts,
  getCreemProducts,
  getPatreonProducts,
  listMappings,
} from '../lib/api'
import { entitlementKeyForProduct, ruleForProduct } from '../lib/mappingKeys'
import { embedScript } from '../lib/publicUrls'
import type { PricingTableData, PricingFeatureIcon, ProductMapping } from '../types/api'

const session = useSessionStore()

interface Product { id: string; name: string; checkout_url?: string }
interface LocalFeature { text: string; icon: PricingFeatureIcon }
interface LocalTier {
  _key: number
  id?: string
  name: string
  description: string
  price_monthly: string
  price_yearly: string
  trial_days: number | null
  highlight: boolean
  ribbon_text: string
  cta_type: 'custom_url' | 'free_signup' | 'one_time' | 'subscription'
  cta_label: string
  cta_url: string
  features: LocalFeature[]
  selectedProductId: string
  // PG-322: the yearly product of a toggled subscription tier, same provider.
  selectedProductIdYearly: string
  cta_url_yearly: string
  existingMappingIdYearly: number | null
  selectedProvider: 'polar' | 'lemonsqueezy' | 'paypal' | 'gumroad' | 'paddle' | 'kofi' | 'creem' | 'patreon'
  mappingEventType: 'order.paid' | 'subscription.active'
  mappingGhostSubscribed: boolean
  mappingEmailType: 'signin' | 'signup' | 'subscribe' | ''
  existingMappingId: number | null
}

let _tierKey = 0
const newTierKey = () => ++_tierKey

function defaultTier(partial: Partial<LocalTier> = {}): LocalTier {
  return {
    _key: newTierKey(),
    name: '',
    description: '',
    price_monthly: '',
    price_yearly: '',
    trial_days: null,
    highlight: false,
    ribbon_text: '',
    cta_type: 'custom_url',
    cta_label: 'Get started',
    cta_url: '',
    features: [],
    selectedProductId: '',
    selectedProductIdYearly: '',
    cta_url_yearly: '',
    existingMappingIdYearly: null,
    selectedProvider: 'polar',
    mappingEventType: 'order.paid',
    mappingGhostSubscribed: true,
    mappingEmailType: 'signin',
    existingMappingId: null,
    ...partial,
  }
}

const tables = ref<PricingTableData[]>([])
const loading = ref(false)
const editorOpen = ref(false)
const editingId = ref<string | null>(null)

const formName = ref('')
const formTemplate = ref<'classic' | 'minimal' | 'bold'>('classic')
const formAccentColor = ref('#4f46e5')
const formCurrency = ref<'EUR' | 'USD' | 'GBP' | 'CHF'>('EUR')
const formTiers = ref<LocalTier[]>([defaultTier({ cta_type: 'free_signup', cta_label: 'Sign up free' })])
// PG-320: the toggle used to switch itself on whenever a tier was a
// subscription, with no way to turn it off. A creator with separate monthly
// and yearly products wants two columns, not one column with a switch. The
// choice is stored on the table; the switch only shows once a subscription
// tier exists, because it means nothing without one.
const hasSubscriptionTier = computed(() => formTiers.value.some(t => t.cta_type === 'subscription'))
const formToggleEnabled = ref(false)
const formShowToggle = computed(() => hasSubscriptionTier.value && formToggleEnabled.value)

// Choosing the toggle is choosing subscriptions: a one-time or custom tier
// cannot have a monthly and a yearly price, so it becomes a subscription the
// moment the toggle is switched on. Free tiers stay free. Nothing is converted
// back when the toggle goes off, there is nothing to restore it to.
watch(formToggleEnabled, (on) => {
  if (!on) return
  for (const tier of formTiers.value) {
    if (tier.cta_type === 'one_time' || tier.cta_type === 'custom_url') tier.cta_type = 'subscription'
  }
})

// With the toggle off a subscription tier has one price and one period. The
// value still lives in price_monthly or price_yearly, so the embed and the
// overlay know which suffix to show without a new field.
function tierPeriod(tier: LocalTier): 'mo' | 'yr' {
  return tier.price_yearly && !tier.price_monthly ? 'yr' : 'mo'
}
function singlePrice(tier: LocalTier): string {
  return tier.price_monthly || tier.price_yearly
}
function setSinglePrice(tier: LocalTier, value: string) {
  if (tierPeriod(tier) === 'yr') { tier.price_yearly = value; tier.price_monthly = '' }
  else { tier.price_monthly = value; tier.price_yearly = '' }
}
function setTierPeriod(tier: LocalTier, period: 'mo' | 'yr') {
  const value = singlePrice(tier)
  if (period === 'yr') { tier.price_yearly = value; tier.price_monthly = '' }
  else { tier.price_monthly = value; tier.price_yearly = '' }
}

const saving = ref(false)
const saveError = ref<string | null>(null)
const saveErrorPlan = ref<string | null>(null)
const justSaved = ref<PricingTableData | null>(null)
const copiedSnippet = ref(false)
const copiedOverlay = ref(false)
const deletingId = ref<string | null>(null)
const overlayLabel = ref('View plans')
const overlayBgColor = ref('#4f46e5')
const overlayRadius = ref<'none' | 'md' | 'full'>('md')
const overlayAlign = ref<'left' | 'center' | 'right'>('center')

const polarProducts = ref<Product[]>([])
const polarProductsLoading = ref(false)
const polarProductsError = ref<string | null>(null)
const polarSandbox = ref(false)

const lsProducts = ref<Product[]>([])
const lsProductsLoading = ref(false)
const lsProductsError = ref<string | null>(null)

const paypalProducts = ref<Product[]>([])
const paypalProductsLoading = ref(false)
const paypalProductsError = ref<string | null>(null)

const gumroadProducts = ref<Product[]>([])
const gumroadProductsLoading = ref(false)
const gumroadProductsError = ref<string | null>(null)

const paddleProducts = ref<Product[]>([])
const paddleProductsLoading = ref(false)
const paddleProductsError = ref<string | null>(null)

const creemProducts = ref<Product[]>([])
const creemProductsLoading = ref(false)
const creemProductsError = ref<string | null>(null)

const patreonProducts = ref<Product[]>([])
const patreonProductsLoading = ref(false)
const patreonProductsError = ref<string | null>(null)

const allProducts = computed(() => [...polarProducts.value, ...lsProducts.value, ...paypalProducts.value, ...gumroadProducts.value, ...paddleProducts.value, ...creemProducts.value, ...patreonProducts.value])

type ProviderKey = 'polar' | 'lemonsqueezy' | 'paypal' | 'gumroad' | 'paddle' | 'kofi' | 'creem' | 'patreon'

function productsForProvider(provider: ProviderKey): Product[] {
  if (provider === 'polar') return polarProducts.value
  if (provider === 'paypal') return paypalProducts.value
  if (provider === 'gumroad') return gumroadProducts.value
  if (provider === 'paddle') return paddleProducts.value
  if (provider === 'creem') return creemProducts.value
  if (provider === 'patreon') return patreonProducts.value
  return lsProducts.value
}

function productsLoadingForProvider(provider: ProviderKey): boolean {
  if (provider === 'polar') return polarProductsLoading.value
  if (provider === 'paypal') return paypalProductsLoading.value
  if (provider === 'gumroad') return gumroadProductsLoading.value
  if (provider === 'paddle') return paddleProductsLoading.value
  if (provider === 'creem') return creemProductsLoading.value
  if (provider === 'patreon') return patreonProductsLoading.value
  return lsProductsLoading.value
}

function productsErrorForProvider(provider: ProviderKey): string | null {
  if (provider === 'polar') return polarProductsError.value
  if (provider === 'paypal') return paypalProductsError.value
  if (provider === 'gumroad') return gumroadProductsError.value
  if (provider === 'paddle') return paddleProductsError.value
  if (provider === 'creem') return creemProductsError.value
  if (provider === 'patreon') return patreonProductsError.value
  return lsProductsError.value
}

const mappings = ref<ProductMapping[]>([])

const isEditing = computed(() => editingId.value !== null)

async function loadTables() {
  if (!session.activeTenantSlug || !session.idToken) return
  loading.value = true
  try {
    tables.value = await listPricingTables(session.activeTenantSlug, session.idToken)
  } finally {
    loading.value = false
  }
}

async function loadPolarProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  polarProductsLoading.value = true
  polarProductsError.value = null
  try {
    const result = await getPolarProducts(session.activeTenantSlug, session.idToken)
    polarProducts.value = result.products ?? []
    polarSandbox.value = result.sandbox ?? false
    if (!result.has_token) polarProductsError.value = 'No Polar token configured.'
  } catch {
    polarProductsError.value = 'Could not load Polar products.'
  } finally {
    polarProductsLoading.value = false
  }
}

async function loadLsProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  lsProductsLoading.value = true
  lsProductsError.value = null
  try {
    const result = await getLemonSqueezyProducts(session.activeTenantSlug, session.idToken)
    lsProducts.value = result.products ?? []
    if (!result.has_token) lsProductsError.value = 'No Lemon Squeezy API key configured.'
    else if (result.needs_store) lsProductsError.value = 'Select your Lemon Squeezy store in the connection settings to load products.'
    else if (result.error) lsProductsError.value = result.error
  } catch {
    lsProductsError.value = 'Could not load Lemon Squeezy products.'
  } finally {
    lsProductsLoading.value = false
  }
}

async function loadPayPalProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  paypalProductsLoading.value = true
  paypalProductsError.value = null
  try {
    const result = await getPayPalProducts(session.activeTenantSlug, session.idToken)
    paypalProducts.value = result.products ?? []
    if (!result.has_token) paypalProductsError.value = 'No PayPal credentials configured. Connect PayPal first.'
    else if (result.error) paypalProductsError.value = result.error
  } catch {
    paypalProductsError.value = 'Could not load PayPal plans.'
  } finally {
    paypalProductsLoading.value = false
  }
}

async function loadGumroadProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  gumroadProductsLoading.value = true
  gumroadProductsError.value = null
  try {
    const result = await getGumroadProducts(session.activeTenantSlug, session.idToken)
    gumroadProducts.value = result.products ?? []
    if (!result.has_token) gumroadProductsError.value = 'No Gumroad credentials configured. Connect Gumroad first.'
    else if (result.error) gumroadProductsError.value = result.error
  } catch {
    gumroadProductsError.value = 'Could not load Gumroad products.'
  } finally {
    gumroadProductsLoading.value = false
  }
}

async function loadPaddleProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  paddleProductsLoading.value = true
  paddleProductsError.value = null
  try {
    const result = await getPaddleProducts(session.activeTenantSlug, session.idToken)
    paddleProducts.value = result.products ?? []
    if (!result.has_token) paddleProductsError.value = 'No Paddle credentials configured. Connect Paddle first.'
    else if (result.error) paddleProductsError.value = result.error
  } catch {
    paddleProductsError.value = 'Could not load Paddle products.'
  } finally {
    paddleProductsLoading.value = false
  }
}

async function loadPatreonProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  patreonProductsLoading.value = true
  patreonProductsError.value = null
  try {
    const result = await getPatreonProducts(session.activeTenantSlug, session.idToken)
    patreonProducts.value = result.products ?? []
    if (!result.has_token) patreonProductsError.value = 'No Patreon credentials configured. Connect Patreon first.'
    else if (result.error) patreonProductsError.value = result.error
  } catch {
    patreonProductsError.value = 'Could not load Patreon tiers.'
  } finally {
    patreonProductsLoading.value = false
  }
}

async function loadCreemProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  creemProductsLoading.value = true
  creemProductsError.value = null
  try {
    const result = await getCreemProducts(session.activeTenantSlug, session.idToken)
    creemProducts.value = result.products ?? []
    if (!result.has_token) creemProductsError.value = 'No Creem credentials configured. Connect Creem first.'
    else if (result.error) creemProductsError.value = result.error
  } catch {
    creemProductsError.value = 'Could not load Creem products.'
  } finally {
    creemProductsLoading.value = false
  }
}

async function loadMappings() {
  if (!session.activeTenantSlug || !session.idToken) return
  try {
    mappings.value = await listMappings(session.activeTenantSlug, session.idToken)
  } catch { /* non-fatal */ }
}

function syncTierMappingState(tier: LocalTier) {
  if (!tier.selectedProductId) return
  const m = ruleForProduct(mappings.value, tier.selectedProvider, tier.selectedProductId)
  if (m) {
    tier.existingMappingId = m.id
    tier.mappingEventType = (m.event_type as 'order.paid' | 'subscription.active') || 'order.paid'
    tier.mappingGhostSubscribed = m.metadata?.ghost_subscribed ?? true
    const emailTypes = m.metadata?.ghost_email_types ?? (m.metadata?.ghost_email_type ? [m.metadata.ghost_email_type] : ['signin'])
    tier.mappingEmailType = (emailTypes[0] as 'signin' | 'signup' | 'subscribe') ?? 'signin'
  } else {
    tier.existingMappingId = null
    tier.mappingEventType = 'order.paid'
    tier.mappingGhostSubscribed = true
    tier.mappingEmailType = 'signin'
  }
}

function checkoutUrlForProduct(tier: LocalTier, id: string): string {
  return productsForProvider(tier.selectedProvider).find(p => p.id === id)?.checkout_url ?? ''
}

function productIdForUrl(url: string): { id: string; provider: ProviderKey } {
  if (!url) return { id: '', provider: 'polar' }
  const polar = polarProducts.value.find(p => p.checkout_url === url)
  if (polar) return { id: polar.id, provider: 'polar' }
  const ls = lsProducts.value.find(p => p.checkout_url === url)
  if (ls) return { id: ls.id, provider: 'lemonsqueezy' }
  const gumroad = gumroadProducts.value.find(p => p.checkout_url === url)
  if (gumroad) return { id: gumroad.id, provider: 'gumroad' }
  return { id: '', provider: 'polar' }
}

// Re-resolve selectedProductId for tiers that loaded before products arrived
watch(allProducts, () => {
  formTiers.value.forEach(tier => {
    if (tier.cta_url && !tier.selectedProductId) {
      const { id, provider } = productIdForUrl(tier.cta_url)
      tier.selectedProductId = id
      tier.selectedProvider = provider
      syncTierMappingState(tier)
    }
  })
})

/** Picking a provider clears the product, because ids do not carry across. */
function setTierProvider(tier: LocalTier, provider: LocalTier['selectedProvider']) {
  tier.selectedProvider = provider
  tier.selectedProductId = ''
  tier.selectedProductIdYearly = ''
  tier.cta_url_yearly = ''
  tier.existingMappingIdYearly = null
}

function resetForm() {
  editingId.value = null
  formName.value = ''
  formTemplate.value = 'classic'
  formAccentColor.value = '#4f46e5'
  formCurrency.value = 'EUR'
  formToggleEnabled.value = false
  // A table almost always opens with the free tier; the paid ones come after it.
  formTiers.value = [defaultTier({ cta_type: 'free_signup', cta_label: 'Sign up free' })]
  saveError.value = null
  justSaved.value = null
  editorOpen.value = false

  overlayLabel.value = 'View plans'
  overlayBgColor.value = '#4f46e5'
  overlayRadius.value = 'md'
  overlayAlign.value = 'center'
}

// The shell asks the page to start over when its nav item or breadcrumb is clicked again.
const pageReset = usePageResetStore()
watch(() => pageReset.tick, () => { if (editorOpen.value) resetForm() })

function openNew() {
  resetForm()
  editorOpen.value = true
  saveError.value = null
  justSaved.value = null
}

function startEdit(table: PricingTableData) {
  justSaved.value = null
  editingId.value = table.id
  formName.value = table.name
  formTemplate.value = table.template
  formAccentColor.value = table.accent_color || '#4f46e5'
  formCurrency.value = (table.currency as 'EUR' | 'USD' | 'GBP' | 'CHF') || 'EUR'
  formToggleEnabled.value = table.show_toggle !== false
  const KNOWN_PROVIDERS = ['polar', 'lemonsqueezy', 'paypal', 'gumroad', 'paddle', 'kofi', 'creem', 'patreon'] as const
  formTiers.value = table.tiers.map(t => {
    // Tiers saved since PR (product_provider/product_id) restore directly --
    // older tiers fall back to the legacy guess (cta_url matched against live
    // product lists), same fix as BuyButton/Paywall (527d75d). Ko-fi has no
    // checkout_url to match, so it only ever works via the persisted fields.
    const persisted = t.product_id && (KNOWN_PROVIDERS as readonly string[]).includes(t.product_provider || '')
    const { id: pId, provider: pProv } = persisted
      ? { id: t.product_id!, provider: t.product_provider as LocalTier['selectedProvider'] }
      : productIdForUrl(t.cta_url)
    const em = pId ? ruleForProduct(mappings.value, pProv, pId) : undefined
    const emEmailTypes = em?.metadata?.ghost_email_types ?? (em?.metadata?.ghost_email_type ? [em.metadata.ghost_email_type] : ['signin'])
    return defaultTier({
      id: t.id,
      name: t.name,
      description: t.description,
      price_monthly: t.price_monthly,
      price_yearly: t.price_yearly,
      trial_days: t.trial_days,
      highlight: t.highlight,
      ribbon_text: t.ribbon_text,
      cta_type: t.cta_type,
      cta_label: t.cta_label,
      cta_url: t.cta_url,
      selectedProductId: pId,
      selectedProductIdYearly: t.product_id_yearly || '',
      cta_url_yearly: t.cta_url_yearly || '',
      existingMappingIdYearly: t.product_id_yearly ? (ruleForProduct(mappings.value, pProv, t.product_id_yearly)?.id ?? null) : null,
      selectedProvider: pProv,
      mappingEventType: (em?.event_type as 'order.paid' | 'subscription.active') || 'order.paid',
      mappingGhostSubscribed: em?.metadata?.ghost_subscribed ?? true,
      mappingEmailType: (emEmailTypes[0] as 'signin' | 'signup' | 'subscribe') ?? 'signin',
      existingMappingId: em?.id ?? null,
      features: (t.features ?? []).map(f => ({ ...f })),
    })
  })
  if (formTiers.value.length === 0) formTiers.value = [defaultTier({ cta_type: 'free_signup', cta_label: 'Sign up free' })]
  saveError.value = null
  editorOpen.value = true
}

function addTier() {
  if (formTiers.value.length >= 3) return
  formTiers.value.push(defaultTier({ cta_type: 'subscription', cta_label: 'Subscribe' }))
}

function removeTier(idx: number) {
  if (formTiers.value.length <= 1) return
  formTiers.value.splice(idx, 1)
}

function toggleHighlight(idx: number) {
  const tier = formTiers.value[idx]
  if (!tier) return
  const current = tier.highlight
  formTiers.value.forEach(t => { t.highlight = false })
  tier.highlight = !current
  if (!tier.highlight) tier.ribbon_text = ''
  else if (!tier.ribbon_text) tier.ribbon_text = 'Popular'
}

function addFeature(tier: LocalTier) {
  tier.features.push({ text: '', icon: 'check' })
}

function removeFeature(tier: LocalTier, idx: number) {
  tier.features.splice(idx, 1)
}

function setFeatureIcon(tier: LocalTier, idx: number, icon: PricingFeatureIcon) {
  const feat = tier.features[idx]
  if (feat) feat.icon = icon
}

// Ko-fi has no product dropdown (no API to fetch tiers/shop items), so its
// field is manual text entry -- mirrors BuyButtonView/PaywallConfigView.
// Pasting a full shop-item share link (ko-fi.com/s/<code>) extracts the
// code we actually need for the mapping and fills the CTA URL with the
// pasted link so the tier has somewhere to send buyers.
function onKofiProductInput(tier: LocalTier) {
  const val = tier.selectedProductId
  const m = val.match(/ko-fi\.com\/s\/([A-Za-z0-9]+)/i)
  if (m) {
    if (!tier.cta_url) {
      tier.cta_url = val.startsWith('http') ? val.trim() : `https://${val.trim()}`
    }
    tier.selectedProductId = m[1]
  }
  if (tier.selectedProductId) {
    syncTierMappingState(tier)
  } else {
    tier.existingMappingId = null
    tier.mappingEventType = 'order.paid'
    tier.mappingGhostSubscribed = true
    tier.mappingEmailType = 'signin'
  }
}

function onYearlyProductSelect(tier: LocalTier, productId: string) {
  tier.selectedProductIdYearly = productId
  tier.cta_url_yearly = productId ? checkoutUrlForProduct(tier, productId) : ''
  tier.existingMappingIdYearly = productId
    ? (ruleForProduct(mappings.value, tier.selectedProvider, productId)?.id ?? null)
    : null
}

function onProductSelect(tier: LocalTier, productId: string) {
  tier.selectedProductId = productId
  if (productId) {
    tier.cta_url = checkoutUrlForProduct(tier, productId)
    syncTierMappingState(tier)
  } else {
    tier.existingMappingId = null
    tier.mappingEventType = 'order.paid'
    tier.mappingGhostSubscribed = true
    tier.mappingEmailType = 'signin'
  }
}

// PG-323: what the embed will render, built from the form. The public
// endpoint sends the same shape, so the preview and the live table agree.
// Debounced, because every keystroke would otherwise reload the frame.
const previewConfig = ref<Record<string, unknown>>({})
function buildPreviewConfig(): Record<string, unknown> {
  return {
    id: 'preview',
    template: formTemplate.value,
    show_toggle: formShowToggle.value,
    accent_color: formAccentColor.value || '#4f46e5',
    currency: formCurrency.value,
    tiers: formTiers.value.map((t, i) => ({
      id: String(i),
      position: i,
      name: t.name || 'Tier',
      description: t.description,
      price_monthly: t.price_monthly,
      price_yearly: t.price_yearly,
      trial_days: t.trial_days,
      highlight: t.highlight,
      ribbon_text: t.ribbon_text,
      cta_type: t.cta_type,
      cta_label: t.cta_label,
      cta_url: t.cta_url,
      cta_url_yearly: (formShowToggle.value && t.cta_type === 'subscription') ? t.cta_url_yearly : '',
      features: t.features,
    })),
  }
}
let previewTimer: ReturnType<typeof setTimeout> | null = null
watch(
  [formTemplate, formShowToggle, formAccentColor, formCurrency, formTiers],
  () => {
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = setTimeout(() => { previewConfig.value = buildPreviewConfig() }, 350)
  },
  { deep: true, immediate: true },
)

async function save() {
  if (!session.activeTenantSlug || !session.idToken) return
  saving.value = true
  saveError.value = null
  try {
    const payload = {
      name: formName.value || 'Untitled table',
      template: formTemplate.value,
      show_toggle: formShowToggle.value,
      accent_color: formAccentColor.value || '#4f46e5',
      currency: formCurrency.value,
      tiers: formTiers.value.map((t, i) => ({
        position: i,
        name: t.name || 'Tier',
        description: t.description,
        price_monthly: t.price_monthly,
        price_yearly: t.price_yearly,
        trial_days: t.trial_days || null,
        highlight: t.highlight,
        ribbon_text: t.ribbon_text,
        cta_type: t.cta_type,
        cta_label: t.cta_label,
        cta_url: t.cta_url,
        features: t.features,
        product_provider: (t.selectedProductId || t.selectedProductIdYearly) ? t.selectedProvider : '',
        product_id: t.selectedProductId,
        // Only a toggled subscription tier sells a second product (PG-322).
        product_id_yearly: (formShowToggle.value && t.cta_type === 'subscription') ? t.selectedProductIdYearly : '',
        cta_url_yearly: (formShowToggle.value && t.cta_type === 'subscription') ? t.cta_url_yearly : '',
        // Travels with the tier, so the server can write the rule for this
        // product in the same transaction as the table (PG-254).
        grant: {
          event_type: t.mappingEventType,
          // One key per tier, so the yearly product grants what the monthly one grants (PG-322).
          entitlement_key: entitlementKeyForProduct(t.selectedProductId || t.selectedProductIdYearly || ''),
          metadata: {
            ghost_subscribed: t.mappingGhostSubscribed,
            ghost_email_types: t.mappingEmailType ? [t.mappingEmailType] : [],
            ghost_labels: [] as string[],
            source_type: 'pricing_table',
            source_name: formName.value,
            source_tier: t.name,
          },
        },
      })),
    }
    let saved: PricingTableData
    if (editingId.value) {
      saved = await updatePricingTable(session.activeTenantSlug, session.idToken, editingId.value, payload)
      const idx = tables.value.findIndex(t => t.id === editingId.value)
      if (idx !== -1) tables.value[idx] = saved
    } else {
      saved = await createPricingTable(session.activeTenantSlug, session.idToken, payload)
      tables.value.unshift(saved)
      editingId.value = saved.id
    }
    justSaved.value = saved
    // The rules travel with the tiers now and are written server-side in the
    // same transaction (PG-254), so there is nothing to write here and nothing
    // to check afterwards. Two tiers on the same product are no longer a case
    // to work around either: they resolve to one rule, which is the point.
    if (formTiers.value.some(t => t.selectedProductId)) {
      await loadMappings()
      formTiers.value.forEach(syncTierMappingState)
    }
  } catch (e: unknown) {
    saveError.value = e instanceof Error ? e.message : 'Save failed.'
    saveErrorPlan.value = isPlanLimitError(e) ? planKeyFromError(e) : null
  } finally {
    saving.value = false
  }
}

async function deleteTable(id: string) {
  if (!session.activeTenantSlug || !session.idToken) return
  deletingId.value = id
  try {
    await deletePricingTable(session.activeTenantSlug, session.idToken, id)
    tables.value = tables.value.filter(t => t.id !== id)
    if (editingId.value === id) resetForm()
  } finally {
    deletingId.value = null
  }
}

const embedSnippet = computed(() => {
  const id = justSaved.value?.id ?? editingId.value ?? ''
  if (!id) return ''
  return embedScript('pricing-table.js', { 'data-table-id': id, defer: '' })
})

const overlaySnippet = computed(() => {
  const id = justSaved.value?.id ?? editingId.value ?? ''
  if (!id) return ''
  const label = overlayLabel.value || 'View plans'
  const color = overlayBgColor.value || '#4f46e5'
  const radius = overlayRadius.value || 'md'
  const align = overlayAlign.value || 'center'
  return embedScript('pricing-table.js', {
    'data-table-id': id,
    'data-overlay-label': label,
    'data-overlay-color': color,
    'data-overlay-radius': radius,
    'data-overlay-align': align,
    defer: '',
  })
})

async function copySnippet() {
  if (!embedSnippet.value) return
  await navigator.clipboard.writeText(embedSnippet.value)
  copiedSnippet.value = true
  setTimeout(() => { copiedSnippet.value = false }, 2000)
}

async function copyOverlay() {
  if (!overlaySnippet.value) return
  await navigator.clipboard.writeText(overlaySnippet.value)
  copiedOverlay.value = true
  setTimeout(() => { copiedOverlay.value = false }, 2000)
}

const TIER_TYPES: { value: LocalTier['cta_type']; label: string; hint: string }[] = [
  { value: 'free_signup', label: 'Free sign-up', hint: 'Ghost free member, no payment' },
  { value: 'subscription', label: 'Subscription', hint: 'Monthly or yearly, via your provider' },
  { value: 'one_time', label: 'One-time', hint: 'A single purchase' },
  { value: 'custom_url', label: 'Custom URL', hint: 'Any link, e.g. pay what you want' },
]

const ICON_OPTIONS: { value: PricingFeatureIcon; label: string }[] = [
  { value: 'check', label: '✓' },
  { value: 'dot', label: '•' },
  { value: 'dash', label: '–' },
  { value: 'cross', label: '✕' },
  { value: 'none', label: '∅' },
]

const TEMPLATES = [
  {
    value: 'classic' as const,
    label: 'Classic',
    desc: 'Center tier elevated with shadow and accent border',
  },
  {
    value: 'minimal' as const,
    label: 'Minimal',
    desc: 'Equal columns, clean top border, no shadows',
  },
  {
    value: 'bold' as const,
    label: 'Bold',
    desc: 'Highlighted tier filled with accent background color',
  },
]

onMounted(async () => {
  await loadTables()
  loadPolarProducts()
  loadLsProducts()
  loadPayPalProducts()
  loadGumroadProducts()
  loadPaddleProducts()
  loadCreemProducts()
  loadPatreonProducts()
  loadMappings()
})
</script>

<template>
  <AppShell>
    <div class="space-y-5">

      <PageHeader title="Pricing Tables" description="Build a pricing table with up to 3 tiers and paste the embed snippet into any Ghost HTML card.">
        <template #actions>
          <UiButton variant="primary" size="sm" @click="openNew">
            <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New table
          </UiButton>
        </template>
      </PageHeader>

      <!-- Empty state (only when no editor open and no tables) -->
      <section v-if="!loading && !editorOpen && tables.length === 0" class="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 p-10 text-center">
        <svg class="mx-auto h-10 w-10 text-slate-300" fill="none" stroke="currentColor" stroke-width="1.25" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375z" />
        </svg>
        <p class="mt-3 text-sm font-medium text-slate-500 dark:text-slate-400">No pricing tables yet</p>
        <p class="mt-1 text-xs text-slate-400 dark:text-slate-500">Click "New table" to create your first one.</p>
      </section>

      <!-- Editor -->
      <section v-if="editorOpen" class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div class="border-b border-slate-100 dark:border-slate-800 px-5 py-3.5">
          <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ isEditing ? 'Edit table' : 'New pricing table' }}</p>
        </div>

        <div class="p-5 space-y-6">

          <!-- Internal name -->
          <div>
            <label class="block text-xs font-medium text-slate-700 dark:text-slate-200 mb-1.5">Internal name</label>
            <input
              v-model="formName"
              type="text"
              placeholder="e.g. Main pricing page"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
            />
          </div>

          <!-- Template picker -->
          <div>
            <label class="block text-xs font-medium text-slate-700 dark:text-slate-200 mb-2">Template</label>
            <div class="grid grid-cols-3 gap-2.5">
              <button
                v-for="tmpl in TEMPLATES"
                :key="tmpl.value"
                type="button"
                @click="formTemplate = tmpl.value"
                class="rounded-lg border-2 p-3 text-left transition-all"
                :class="formTemplate === tmpl.value
                  ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10'
                  : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-800 dark:bg-slate-800/40 dark:hover:border-slate-700'"
              >
                <p class="text-xs font-semibold" :class="formTemplate === tmpl.value ? 'text-indigo-700 dark:text-indigo-300' : 'text-slate-700 dark:text-slate-200'">{{ tmpl.label }}</p>
                <p class="mt-0.5 text-[11px] leading-snug" :class="formTemplate === tmpl.value ? 'text-indigo-500' : 'text-slate-400 dark:text-slate-500'">{{ tmpl.desc }}</p>
              </button>
            </div>
          </div>

          <!-- Accent color + Toggle row -->
          <div class="flex items-center gap-6">
            <div class="flex items-center gap-2.5">
              <label for="accent-color" class="text-sm text-slate-700 dark:text-slate-200 whitespace-nowrap">Accent color</label>
              <div class="relative flex items-center gap-2">
                <input
                  id="accent-color"
                  v-model="formAccentColor"
                  type="color"
                  class="h-8 w-8 cursor-pointer rounded border border-slate-300 dark:border-slate-700 p-0.5 bg-white"
                />
                <input
                  v-model="formAccentColor"
                  type="text"
                  maxlength="7"
                  class="w-24 rounded border border-slate-300 dark:border-slate-700 px-2 py-1 text-xs font-mono text-slate-700 dark:text-slate-200 focus:border-indigo-400 focus:outline-none bg-white dark:bg-slate-900"
                  placeholder="#4f46e5"
                />
              </div>
            </div>
            <div class="flex items-center gap-2.5">
              <label class="text-xs font-medium text-slate-500 dark:text-slate-400">Currency</label>
              <select
                v-model="formCurrency"
                class="rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm bg-white dark:bg-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="EUR">EUR (€)</option>
                <option value="USD">USD ($)</option>
                <option value="GBP">GBP (£)</option>
                <option value="CHF">CHF</option>
              </select>
            </div>
          </div>

          <!-- How do you sell? (PG-320): the layout decision, made where it
               can be seen, with an example of each. Only once a tier is a
               subscription, because it means nothing before that. -->
          <div v-if="hasSubscriptionTier" class="space-y-2">
            <p class="text-xs font-medium text-slate-700 dark:text-slate-200">How do you sell?</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" role="radiogroup" aria-label="How do you sell?">
              <label
                class="rounded-xl border-2 p-3.5 cursor-pointer transition-colors"
                :class="!formToggleEnabled ? 'border-indigo-500 bg-indigo-50/40 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'"
              >
                <div class="flex items-start gap-2.5">
                  <input type="radio" name="sell-mode" :value="false" v-model="formToggleEnabled" class="mt-0.5 accent-indigo-600" aria-label="One price per tier" />
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">One price per tier</p>
                    <p class="text-xs text-slate-600 dark:text-slate-400 mt-0.5">Every column has one price and one period. Pick this when monthly and yearly are separate products at your provider, or when you sell a single plan.</p>
                    <div class="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                      <span class="rounded-md border border-slate-200 dark:border-slate-700 px-1.5 py-0.5">Free</span>
                      <span class="rounded-md border border-indigo-300 dark:border-indigo-500/50 px-1.5 py-0.5 font-medium">Monthly <span class="text-slate-400">6 / mo</span></span>
                      <span class="rounded-md border border-slate-200 dark:border-slate-700 px-1.5 py-0.5">Yearly <span class="text-slate-400">60 / yr</span></span>
                    </div>
                  </div>
                </div>
              </label>
              <label
                class="rounded-xl border-2 p-3.5 cursor-pointer transition-colors"
                :class="formToggleEnabled ? 'border-indigo-500 bg-indigo-50/40 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'"
              >
                <div class="flex items-start gap-2.5">
                  <input type="radio" name="sell-mode" :value="true" v-model="formToggleEnabled" class="mt-0.5 accent-indigo-600" aria-label="Monthly / yearly toggle" />
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Monthly / yearly toggle</p>
                    <p class="text-xs text-slate-600 dark:text-slate-400 mt-0.5">Visitors flip the period on the table. Pick this when you have several plans and each exists monthly and yearly. Each tier gets a product for both periods, and the button follows the toggle.</p>
                    <div class="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                      <span class="text-indigo-600 dark:text-indigo-400 font-medium">Monthly</span><span class="inline-block h-3 w-6 rounded-full bg-indigo-500 align-middle"></span><span class="text-slate-400">Yearly</span>
                      <span class="rounded-md border border-slate-200 dark:border-slate-700 px-1.5 py-0.5 ml-1">Basic <span class="text-slate-400">5 / mo</span></span>
                      <span class="rounded-md border border-indigo-300 dark:border-indigo-500/50 px-1.5 py-0.5 font-medium">Premium <span class="text-slate-400">12 / mo</span></span>
                    </div>
                  </div>
                </div>
              </label>
            </div>
          </div>

          <!-- Preview (PG-323): the reader's view, rendered by the embed script itself -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <p class="text-xs font-medium text-slate-700 dark:text-slate-200">Preview</p>
              <p class="text-[11px] text-slate-400 dark:text-slate-500">Updates as you type. Buttons are inactive here.</p>
            </div>
            <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 p-2">
              <PricingTablePreview :config="previewConfig" />
            </div>
          </div>

          <!-- Tiers -->
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <p class="text-xs font-medium text-slate-700 dark:text-slate-200">Tiers ({{ formTiers.length }}/3)</p>
              <button
                v-if="formTiers.length < 3"
                type="button"
                @click="addTier"
                class="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
              >
                <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add tier
              </button>
            </div>

            <div
              v-for="(tier, idx) in formTiers"
              :key="tier._key"
              class="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40/50 p-4 space-y-4"
            >
              <!-- Tier header -->
              <div class="flex items-center justify-between gap-2">
                <p class="text-xs font-semibold text-slate-600 dark:text-slate-300">Tier {{ idx + 1 }}</p>
                <button
                  v-if="formTiers.length > 1"
                  type="button"
                  @click="removeTier(idx)"
                  class="text-slate-400 dark:text-slate-500 hover:text-rose-500 transition-colors"
                  title="Remove tier"
                >
                  <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <!-- Tier type first: it decides which fields follow and what the button does -->
              <div>
                <p class="text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1.5">Tier type</p>
                <div class="grid grid-cols-2 sm:grid-cols-4 gap-1.5" role="radiogroup" aria-label="Tier type">
                  <button
                    v-for="opt in TIER_TYPES"
                    :key="opt.value"
                    type="button"
                    role="radio"
                    :aria-checked="tier.cta_type === opt.value"
                    :aria-label="opt.label"
                    @click="tier.cta_type = opt.value"
                    class="rounded-lg border px-2.5 py-2 text-left transition-colors"
                    :class="tier.cta_type === opt.value
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10 ring-1 ring-indigo-500'
                      : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700'"
                  >
                    <span class="block text-xs font-semibold" :class="tier.cta_type === opt.value ? 'text-indigo-700 dark:text-indigo-300' : 'text-slate-700 dark:text-slate-200'">{{ opt.label }}</span>
                    <span class="block text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{{ opt.hint }}</span>
                  </button>
                </div>
              </div>

              <!-- Name, description, highlight -->
              <div class="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-start">
                <div>
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Name</label>
                  <input v-model="tier.name" type="text" placeholder="Free" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900" />
                </div>
                <div>
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Description</label>
                  <input v-model="tier.description" type="text" placeholder="For everyone" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900" />
                </div>
                <div class="md:pt-[19px]">
                  <div class="flex items-center gap-2">
                      <button
                        type="button"
                        @click="toggleHighlight(idx)"
                        class="flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-[11px] font-medium transition-all"
                        :class="tier.highlight
                          ? 'border-indigo-300 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                          : 'border-slate-200 dark:border-slate-800 bg-white text-slate-600 dark:text-slate-300 hover:border-slate-300 dark:border-slate-700'"
                      >
                        <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                        </svg>
                        {{ tier.highlight ? 'Highlighted' : 'Highlight this tier' }}
                      </button>
                  </div>
                  <div v-if="tier.highlight" class="mt-1.5 w-40">
                    <input
                      v-model="tier.ribbon_text"
                      maxlength="10"
                      type="text"
                      placeholder="Popular"
                      aria-label="Ribbon text"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                    />
                    <p class="mt-0.5 text-[10px] text-slate-400 dark:text-slate-500">Ribbon ({{ tier.ribbon_text.length }}/10)</p>
                  </div>
                </div>
              </div>

              <!-- Pricing -->
              <div
                class="grid gap-3"
                :class="(tier.cta_type === 'one_time' || tier.cta_type === 'free_signup') ? 'grid-cols-2' : (formShowToggle ? 'grid-cols-3' : 'grid-cols-2')"
              >
                <div v-if="tier.cta_type === 'subscription' && !formShowToggle">
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Price</label>
                  <div class="flex gap-1.5">
                    <input
                      :value="singlePrice(tier)"
                      @input="setSinglePrice(tier, ($event.target as HTMLInputElement).value)"
                      type="text"
                      placeholder="€0"
                      aria-label="Price"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                    />
                    <select
                      :value="tierPeriod(tier)"
                      @change="setTierPeriod(tier, ($event.target as HTMLSelectElement).value as 'mo' | 'yr')"
                      aria-label="Billing period"
                      class="shrink-0 rounded-lg border border-slate-300 dark:border-slate-700 px-2 py-1.5 text-sm bg-white dark:bg-slate-900 focus:border-indigo-500 focus:outline-none"
                    >
                      <option value="mo">/ mo</option>
                      <option value="yr">/ yr</option>
                    </select>
                  </div>
                </div>
                <div v-else>
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">
                    {{ tier.cta_type === 'one_time' ? 'Price' : tier.cta_type === 'free_signup' ? 'Display price' : (formShowToggle ? 'Monthly price' : 'Price') }}
                  </label>
                  <input v-model="tier.price_monthly" type="text" placeholder="€0" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900" />
                  <!-- A toggled table shows this tier's one price in both views; say so, or the
                       missing yearly field reads as a bug (staging feedback, 14.09.). -->
                  <p v-if="formShowToggle && (tier.cta_type === 'one_time' || tier.cta_type === 'free_signup')" class="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
                    {{ tier.cta_type === 'one_time' ? 'One-time tier: one price, shown in both views. Switch the call to action to Subscription for a monthly and a yearly price.' : 'Free tier: shown the same in both views.' }}
                  </p>
                </div>
                <div v-if="formShowToggle && tier.cta_type !== 'one_time' && tier.cta_type !== 'free_signup'">
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Yearly price</label>
                  <input v-model="tier.price_yearly" type="text" placeholder="€0" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900" />
                </div>
                <div v-if="tier.cta_type !== 'free_signup' && tier.cta_type !== 'one_time'">
                  <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Trial days</label>
                  <input
                    :value="tier.trial_days ?? ''"
                    @input="tier.trial_days = ($event.target as HTMLInputElement).value ? parseInt(($event.target as HTMLInputElement).value) : null"
                    type="number"
                    min="0"
                    placeholder="—"
                    class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                  />
                </div>
              </div>

              <!-- CTA -->
              <div class="space-y-2">
                <p class="text-[11px] font-medium text-slate-600 dark:text-slate-300">Button label</p>
                <div class="grid grid-cols-1 gap-2">
                  <input v-model="tier.cta_label" type="text" placeholder="Get started" aria-label="Button label" class="rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900" />
                </div>
                <!-- Free Sign-Up info box -->
                <div v-if="tier.cta_type === 'free_signup'" class="rounded-lg border border-indigo-100 dark:border-indigo-500/30 bg-indigo-50 dark:bg-indigo-500/10 px-3 py-2.5 text-[11px] text-indigo-700 dark:text-indigo-300 leading-relaxed">
                  Visitors who click this button will be redirected to your Ghost free member signup. No payment required, no URL to enter.
                </div>
                <!-- Product picker for paid types -->
                <div v-if="tier.cta_type === 'one_time' || tier.cta_type === 'subscription'" class="space-y-1.5">
                  <ProviderPicker :model-value="tier.selectedProvider" @update:model-value="v => setTierProvider(tier, v as typeof tier.selectedProvider)" />
                  <p v-if="formShowToggle && tier.cta_type === 'subscription'" class="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">Monthly product</p>
                  <template v-if="tier.selectedProvider === 'kofi'">
                    <input
                      v-model="tier.selectedProductId"
                      @input="onKofiProductInput(tier)"
                      type="text"
                      placeholder="Paste a shop item link (ko-fi.com/s/...), a tier name, or kofi-support"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                    />
                    <p class="text-[10px] text-slate-400 dark:text-slate-500">For shop items, just paste the item's share link (Share &rarr; Copy link, e.g. <code>ko-fi.com/s/c0e30e5fcf</code>), we extract the item code and fill the checkout URL for you. For memberships, type the exact tier name as it appears on your Ko-fi page. Use <code>kofi-support</code> for plain tips.</p>
                  </template>
                  <template v-else>
                    <select
                      :value="tier.selectedProductId"
                      @change="onProductSelect(tier, ($event.target as HTMLSelectElement).value)"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                      :disabled="productsLoadingForProvider(tier.selectedProvider)"
                    >
                      <option value="">
                        {{ productsLoadingForProvider(tier.selectedProvider) ? 'Loading...' :
                           productsErrorForProvider(tier.selectedProvider) ? 'No products available' : 'Select a product' }}
                      </option>
                      <option v-for="p in productsForProvider(tier.selectedProvider)" :key="p.id" :value="p.id">{{ p.name }}</option>
                    </select>
                    <p v-if="polarSandbox && tier.selectedProvider === 'polar'" class="text-[10px] text-amber-600 dark:text-amber-400">Sandbox mode, using test products</p>
                    <p v-if="productsErrorForProvider(tier.selectedProvider)" class="text-[10px] text-amber-600 dark:text-amber-400">{{ productsErrorForProvider(tier.selectedProvider) }}</p>
                    <p v-if="tier.selectedProvider === 'paddle'" class="text-[10px] text-slate-400 dark:text-slate-500">Paddle checkout is driven client-side and has no direct checkout link. Enter your Paddle checkout link manually after selecting a product.</p>
                  </template>
                  <!-- PG-322: second product for the yearly view of a toggled tier -->
                  <div v-if="formShowToggle && tier.cta_type === 'subscription'" class="rounded-lg border border-slate-200 dark:border-slate-800 p-2.5 space-y-1.5">
                    <p class="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">Yearly product</p>
                    <template v-if="tier.selectedProvider === 'kofi'">
                      <input
                        v-model="tier.selectedProductIdYearly"
                        type="text"
                        placeholder="Yearly tier name or shop item code"
                        aria-label="Yearly product"
                        class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                      />
                    </template>
                    <select
                      v-else
                      :value="tier.selectedProductIdYearly"
                      @change="onYearlyProductSelect(tier, ($event.target as HTMLSelectElement).value)"
                      aria-label="Yearly product"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                      :disabled="productsLoadingForProvider(tier.selectedProvider)"
                    >
                      <option value="">Select the yearly product</option>
                      <option v-for="p in productsForProvider(tier.selectedProvider)" :key="p.id" :value="p.id">{{ p.name }}</option>
                    </select>
                    <input
                      v-model="tier.cta_url_yearly"
                      type="url"
                      placeholder="Yearly checkout URL (auto-filled from the product)"
                      aria-label="Yearly checkout URL"
                      class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                    />
                    <p class="text-[10px] text-slate-400 dark:text-slate-500">
                      Visitors who switch to yearly buy this product. It grants the same access as the monthly one.
                      <span v-if="tier.selectedProductIdYearly" :class="tier.existingMappingIdYearly !== null ? 'text-emerald-600' : 'text-rose-600'">{{ tier.existingMappingIdYearly !== null ? 'Mapped.' : 'Rule is created on save.' }}</span>
                    </p>
                  </div>
                  <!-- Ghost actions mapping -->
                  <div v-if="tier.selectedProductId" class="rounded-lg border border-indigo-100 dark:border-indigo-500/30 bg-indigo-50/40 dark:bg-indigo-500/10 px-3 py-2.5 space-y-2">
                    <div class="flex items-center justify-between">
                      <p class="text-[10px] font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Ghost actions</p>
                      <span v-if="tier.existingMappingId !== null" class="inline-flex items-center gap-0.5 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
                        <svg class="h-2 w-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                        Mapped
                      </span>
                      <span v-else class="inline-flex items-center gap-0.5 rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"><svg class="h-2 w-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>Not mapped</span>
                    </div>
                    <!-- Trigger -->
                    <div class="grid grid-cols-2 gap-1">
                      <button type="button"
                        class="flex items-center gap-1.5 rounded border px-2 py-1.5 text-left transition-colors"
                        :class="tier.mappingEventType === 'order.paid' ? 'border-indigo-300 bg-white dark:border-indigo-500/50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 bg-white/60 hover:bg-white dark:bg-slate-800/40 dark:hover:bg-slate-800'"
                        @click="tier.mappingEventType = 'order.paid'">
                        <div class="h-3 w-3 rounded-full border-2 flex items-center justify-center shrink-0"
                          :class="tier.mappingEventType === 'order.paid' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300 dark:border-slate-700'">
                          <div v-if="tier.mappingEventType === 'order.paid'" class="h-1 w-1 rounded-full bg-white" />
                        </div>
                        <span class="text-[10px] font-medium text-slate-700 dark:text-slate-200">One-time</span>
                      </button>
                      <button type="button"
                        class="flex items-center gap-1.5 rounded border px-2 py-1.5 text-left transition-colors"
                        :class="tier.mappingEventType === 'subscription.active' ? 'border-indigo-300 bg-white dark:border-indigo-500/50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 bg-white/60 hover:bg-white dark:bg-slate-800/40 dark:hover:bg-slate-800'"
                        @click="tier.mappingEventType = 'subscription.active'">
                        <div class="h-3 w-3 rounded-full border-2 flex items-center justify-center shrink-0"
                          :class="tier.mappingEventType === 'subscription.active' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300 dark:border-slate-700'">
                          <div v-if="tier.mappingEventType === 'subscription.active'" class="h-1 w-1 rounded-full bg-white" />
                        </div>
                        <span class="text-[10px] font-medium text-slate-700 dark:text-slate-200">Subscription</span>
                      </button>
                    </div>
                    <!-- Newsletter + email in one row -->
                    <div class="flex items-center gap-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 py-1.5">
                      <span class="text-[10px] text-slate-600 dark:text-slate-300 shrink-0">Newsletter</span>
                      <label class="flex items-center gap-0.5 cursor-pointer text-[10px] text-slate-700 dark:text-slate-200">
                        <input type="radio" :value="true" v-model="tier.mappingGhostSubscribed" class="accent-indigo-600 h-3 w-3" /> Yes
                      </label>
                      <label class="flex items-center gap-0.5 cursor-pointer text-[10px] text-slate-700 dark:text-slate-200">
                        <input type="radio" :value="false" v-model="tier.mappingGhostSubscribed" class="accent-indigo-600 h-3 w-3" /> No
                      </label>
                    </div>
                    <select v-model="tier.mappingEmailType" class="w-full rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 py-1 text-[10px] text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                      <option value="signin">Magic Link (recommended)</option>
                      <option value="signup">Account confirmation</option>
                      <option value="subscribe">Newsletter opt-in</option>
                      <option value="">No email</option>
                    </select>
                  </div>
                </div>
                <!-- PWYW hint for custom_url -->
                <div v-if="tier.cta_type === 'custom_url'" class="rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40 px-3 py-2 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
                  You can also use this for Pay What You Want (PWYW). Just paste your payment provider's PWYW checkout link here.
                </div>
                <!-- URL input for custom_url and paid types -->
                <div v-if="tier.cta_type !== 'free_signup'">
                  <label class="block text-[11px] text-slate-500 dark:text-slate-400 mb-1">{{ tier.cta_type === 'custom_url' ? 'URL' : 'Checkout URL (auto-filled from product or enter manually)' }}</label>
                  <input
                    v-model="tier.cta_url"
                    type="url"
                    placeholder="https://"
                    class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                  />
                </div>
              </div>

              <!-- Features -->
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <p class="text-[11px] font-medium text-slate-600 dark:text-slate-300">Features</p>
                  <button
                    type="button"
                    @click="addFeature(tier)"
                    class="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:border-slate-300 dark:border-slate-700 hover:text-slate-800 dark:text-slate-100"
                  >
                    <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    Add
                  </button>
                </div>
                <div v-if="tier.features.length === 0" class="text-[11px] text-slate-400 dark:text-slate-500 py-1">
                  No features yet.
                </div>
                <div
                  v-for="(feat, fi) in tier.features"
                  :key="fi"
                  class="flex items-center gap-2"
                >
                  <!-- Icon picker -->
                  <div class="flex shrink-0 items-center gap-0.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-0.5">
                    <button
                      v-for="ico in ICON_OPTIONS"
                      :key="ico.value"
                      type="button"
                      @click="setFeatureIcon(tier, fi, ico.value)"
                      class="w-7 h-6 rounded text-center text-sm leading-none transition-colors"
                      :class="feat.icon === ico.value ? 'bg-indigo-100 text-indigo-700 dark:text-indigo-300 font-bold' : 'text-slate-400 dark:text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'"
                      :title="ico.value"
                    >{{ ico.label }}</button>
                  </div>
                  <input
                    v-model="feat.text"
                    type="text"
                    placeholder="Feature description"
                    class="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
                  />
                  <button
                    type="button"
                    @click="removeFeature(tier, fi)"
                    class="shrink-0 text-slate-300 hover:text-rose-400 transition-colors"
                  >
                    <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Error -->
          <UpgradeBanner v-if="saveError && saveErrorPlan" :message="saveError" :plan-key="saveErrorPlan" />
          <p v-else-if="saveError" class="text-sm text-rose-600 dark:text-rose-400 rounded-lg bg-rose-50 dark:bg-rose-500/10 px-3 py-2 border border-rose-200 dark:border-rose-500/30">{{ saveError }}</p>

          <!-- Actions -->
          <div class="flex items-center gap-3 pt-1">
            <button
              type="button"
              @click="save"
              :disabled="saving"
              class="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60 transition-colors"
            >
              <svg v-if="saving" class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              {{ saving ? 'Saving...' : isEditing ? 'Save changes' : 'Create table' }}
            </button>
            <button
              type="button"
              @click="resetForm"
              class="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
            >
              Cancel
            </button>
          </div>

        </div>
      </section>

      <!-- Embed options (after save) -->
      <section v-if="(justSaved || editingId) && editorOpen" class="space-y-4">

        <!-- Success header -->
        <div class="flex items-center gap-2 px-1">
          <svg class="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">Table saved. Choose how to embed it</p>
        </div>

        <!-- Option A: Inline embed -->
        <div class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 space-y-3">
          <div>
            <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Option A: Inline embed</p>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Renders the pricing table directly inside a Ghost HTML card. Width is limited by Ghost's content column.</p>
          </div>
          <div class="flex items-center justify-between">
            <p class="text-xs text-slate-500 dark:text-slate-400">Paste into a Ghost HTML card</p>
            <button type="button" @click="copySnippet" class="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <svg v-if="!copiedSnippet" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <svg v-else class="h-3 w-3 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              {{ copiedSnippet ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <pre class="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100"><code>{{ embedSnippet }}</code></pre>
        </div>

        <!-- Option B: Overlay button -->
        <div class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 space-y-3">
          <div>
            <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Option B: Overlay button</p>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Renders a styled button anywhere on your page. Clicking it opens the full pricing table in a full-screen overlay, with no width constraints.</p>
          </div>
          <!-- Button label -->
          <div>
            <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Button label</label>
            <input
              v-model="overlayLabel"
              type="text"
              placeholder="View plans"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900"
            />
          </div>
          <!-- Button style options -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Button color</label>
              <div class="flex items-center gap-1.5">
                <input v-model="overlayBgColor" type="color" class="h-8 w-8 cursor-pointer rounded border border-slate-300 dark:border-slate-700 p-0.5 bg-white shrink-0" />
                <input v-model="overlayBgColor" type="text" maxlength="7" class="w-full rounded border border-slate-300 dark:border-slate-700 px-2 py-1.5 text-xs font-mono text-slate-700 dark:text-slate-200 focus:border-indigo-400 focus:outline-none bg-white dark:bg-slate-900" placeholder="#4f46e5" />
              </div>
            </div>
            <div>
              <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Corners</label>
              <select v-model="overlayRadius" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900">
                <option value="md">Rounded</option>
                <option value="full">Pill</option>
                <option value="none">Flat</option>
              </select>
            </div>
            <div>
              <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300 mb-1">Alignment</label>
              <select v-model="overlayAlign" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white dark:bg-slate-900">
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </div>
          </div>
          <div class="flex items-center justify-between">
            <p class="text-xs text-slate-500 dark:text-slate-400">Paste into any Ghost HTML card or text block</p>
            <button type="button" @click="copyOverlay" class="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <svg v-if="!copiedOverlay" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <svg v-else class="h-3 w-3 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              {{ copiedOverlay ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <pre class="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100"><code>{{ overlaySnippet }}</code></pre>
        </div>

      </section>

      <!-- Saved tables list (below editor) -->
      <section v-if="tables.length > 0" class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div class="border-b border-slate-100 dark:border-slate-800 px-5 py-3">
          <p class="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Saved tables</p>
        </div>
        <ul class="divide-y divide-slate-100">
          <li
            v-for="table in tables"
            :key="table.id"
            class="flex items-center gap-2 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
            :class="editingId === table.id ? 'bg-indigo-50/60 dark:bg-indigo-500/10' : ''"
          >
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-500/10 text-indigo-500">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375z" />
              </svg>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{{ table.name }}</p>
              <p class="text-xs text-slate-400 dark:text-slate-500 capitalize">{{ table.template }} &middot; {{ table.tiers.length }} tier{{ table.tiers.length !== 1 ? 's' : '' }}</p>
            </div>
            <button
              type="button"
              @click="startEdit(table)"
              class="shrink-0 flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:border-indigo-300 hover:text-indigo-600 transition-colors"
              :class="editingId === table.id ? 'border-indigo-300 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400' : ''"
              title="Edit table"
            >
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
              </svg>
              {{ editingId === table.id ? 'Editing' : 'Edit' }}
            </button>
            <button
              type="button"
              :disabled="deletingId === table.id"
              @click.stop="deleteTable(table.id)"
              class="shrink-0 rounded p-1.5 text-slate-400 dark:text-slate-500 hover:bg-rose-50 hover:text-rose-500 disabled:opacity-50 transition-colors"
              title="Delete table"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
            </button>
          </li>
        </ul>
      </section>

    </div>
  </AppShell>
</template>
