// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import UpgradeBanner from '../components/UpgradeBanner.vue'
import { PageHeader } from '../components/ui'
import { useSessionStore } from '../stores/session'
import { isPlanLimitError, planKeyFromError } from '../lib/planUpgrade'
import {
  listBuyButtons,
  createBuyButton,
  updateBuyButton,
  deleteBuyButton,
  getPolarProducts,
  getLemonSqueezyProducts,
  getPayPalProducts,
  getGumroadProducts,
  getPaddleProducts,
  getCreemProducts,
  getPatreonProducts,
  listMappings,
  createMapping,
  updateMapping,
  type BuyButtonData,
} from '../lib/api'
import type { ProductMapping } from '../types/api'

const session = useSessionStore()

interface Product { id: string; name: string; checkout_url?: string }

const selectedProvider = ref<'polar' | 'lemonsqueezy' | 'paypal' | 'gumroad' | 'paddle' | 'kofi' | 'creem' | 'patreon'>('polar')
const isManualProduct = computed(() => selectedProvider.value === 'kofi')

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

const activeProducts = computed(() => {
  if (selectedProvider.value === 'polar') return polarProducts.value
  if (selectedProvider.value === 'paypal') return paypalProducts.value
  if (selectedProvider.value === 'gumroad') return gumroadProducts.value
  if (selectedProvider.value === 'paddle') return paddleProducts.value
  if (selectedProvider.value === 'creem') return creemProducts.value
  if (selectedProvider.value === 'patreon') return patreonProducts.value
  return lsProducts.value
})
const productsLoading = computed(() => {
  if (selectedProvider.value === 'polar') return polarProductsLoading.value
  if (selectedProvider.value === 'paypal') return paypalProductsLoading.value
  if (selectedProvider.value === 'gumroad') return gumroadProductsLoading.value
  if (selectedProvider.value === 'paddle') return paddleProductsLoading.value
  if (selectedProvider.value === 'creem') return creemProductsLoading.value
  if (selectedProvider.value === 'patreon') return patreonProductsLoading.value
  return lsProductsLoading.value
})
const productsError = computed(() => {
  if (selectedProvider.value === 'polar') return polarProductsError.value
  if (selectedProvider.value === 'paypal') return paypalProductsError.value
  if (selectedProvider.value === 'gumroad') return gumroadProductsError.value
  if (selectedProvider.value === 'paddle') return paddleProductsError.value
  if (selectedProvider.value === 'creem') return creemProductsError.value
  if (selectedProvider.value === 'patreon') return patreonProductsError.value
  return lsProductsError.value
})

const useProduct = ref(true)
const selectedProductId = ref('')

const mappings = ref<ProductMapping[]>([])
const existingMappingId = ref<number | null>(null)
const mappingEventType = ref<'order.paid' | 'subscription.active'>('order.paid')
const mappingGhostSubscribed = ref(true)
const mappingEmailType = ref<'signin' | 'signup' | 'subscribe' | ''>('signin')

const buttons = ref<BuyButtonData[]>([])
const loading = ref(false)
const saving = ref(false)
const saveSuccess = ref(false)
const saveError = ref<string | null>(null)
const saveErrorPlan = ref<string | null>(null)
const editingId = ref<string | null>(null)
const copiedRowId = ref<string | null>(null)
const copiedEmbed = ref(false)

const formName = ref('')
const formLabel = ref('Buy now')
const formDescription = ref('')
const formTargetUrl = ref('')
const formBgColor = ref('#4f46e5')
const formTextColor = ref('#ffffff')
const formBorderRadius = ref<'none' | 'md' | 'full'>('md')
const formWidth = ref<'auto' | 'full'>('auto')
const formAlignment = ref<'left' | 'center' | 'right'>('left')
const formTarget = ref<'_blank' | '_self'>('_blank')

const isEditing = computed(() => editingId.value !== null)

const previewStyle = computed(() => ({
  backgroundColor: formBgColor.value,
  color: formTextColor.value,
  padding: '0.5em 1.5em',
  borderRadius: formBorderRadius.value === 'full' ? '9999px' : formBorderRadius.value === 'none' ? '0' : '8px',
  fontSize: '0.875rem',
  fontWeight: '600',
  display: 'inline-block',
  width: formWidth.value === 'full' ? '100%' : 'auto',
  textAlign: formAlignment.value as 'left' | 'center' | 'right',
  boxSizing: 'border-box' as const,
  cursor: 'default',
}))

async function loadPolarProducts() {
  if (!session.activeTenantSlug || !session.idToken) return
  polarProductsLoading.value = true
  polarProductsError.value = null
  try {
    const result = await getPolarProducts(session.activeTenantSlug, session.idToken)
    polarProducts.value = result.products ?? []
    polarSandbox.value = result.sandbox ?? false
    if (!result.has_token) polarProductsError.value = 'No Polar token configured. Connect Polar first to load products.'
  } catch {
    polarProductsError.value = 'Could not load products.'
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
    if (!result.has_token) lsProductsError.value = 'No Lemon Squeezy API key configured. Add it in the Lemon Squeezy connection settings.'
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

function checkoutUrlForProduct(id: string): string | null {
  const p = activeProducts.value.find(p => p.id === id)
  return p?.checkout_url ?? null
}

watch(selectedProductId, (id) => {
  if (useProduct.value && id && !isManualProduct.value) formTargetUrl.value = checkoutUrlForProduct(id) ?? ''
})

// Ko-fi convenience: pasting a full shop-item share link
// (https://ko-fi.com/s/c0e30e5fcf) extracts the code we actually need for
// the mapping, and fills the button URL with the pasted link so the button
// has somewhere to send buyers without a second manual step.
watch(selectedProductId, (val) => {
  if (selectedProvider.value !== 'kofi' || !val) return
  const m = val.match(/ko-fi\.com\/s\/([A-Za-z0-9]+)/i)
  if (!m) return
  if (!formTargetUrl.value) {
    formTargetUrl.value = val.startsWith('http') ? val.trim() : `https://${val.trim()}`
  }
  selectedProductId.value = m[1]
})
watch(useProduct, (val) => {
  if (val && selectedProductId.value && !isManualProduct.value) formTargetUrl.value = checkoutUrlForProduct(selectedProductId.value) ?? ''
})

async function loadMappings() {
  if (!session.activeTenantSlug || !session.idToken) return
  try {
    mappings.value = await listMappings(session.activeTenantSlug, session.idToken)
  } catch { /* non-fatal */ }
}

function syncMappingState(productId: string) {
  const m = mappings.value.find(m => m.external_product_id === productId)
  if (m) {
    existingMappingId.value = m.id
    mappingEventType.value = (m.event_type as 'order.paid' | 'subscription.active') || 'order.paid'
    mappingGhostSubscribed.value = m.metadata?.ghost_subscribed ?? true
    const emailTypes = m.metadata?.ghost_email_types ?? (m.metadata?.ghost_email_type ? [m.metadata.ghost_email_type] : ['signin'])
    mappingEmailType.value = (emailTypes[0] as 'signin' | 'signup' | 'subscribe') ?? 'signin'
  } else {
    existingMappingId.value = null
    mappingEventType.value = 'order.paid'
    mappingGhostSubscribed.value = true
    mappingEmailType.value = 'signin'
  }
}

async function loadButtons() {
  if (!session.activeTenantSlug || !session.idToken) return
  loading.value = true
  try {
    buttons.value = await listBuyButtons(session.activeTenantSlug, session.idToken)
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  formName.value = ''
  formLabel.value = 'Buy now'
  formDescription.value = ''
  formTargetUrl.value = ''
  formBgColor.value = '#4f46e5'
  formTextColor.value = '#ffffff'
  formBorderRadius.value = 'md'
  formWidth.value = 'auto'
  formAlignment.value = 'left'
  formTarget.value = '_blank'
  useProduct.value = true
  selectedProductId.value = ''
  existingMappingId.value = null
  mappingEventType.value = 'order.paid'
  mappingGhostSubscribed.value = true
  mappingEmailType.value = 'signin'
  saveError.value = null
}

function toggleUseProduct() {
  useProduct.value = !useProduct.value
  if (!useProduct.value) {
    formTargetUrl.value = ''
    selectedProductId.value = ''
  }
}

function startEdit(btn: BuyButtonData) {
  editingId.value = btn.id
  formName.value = btn.name
  formLabel.value = btn.label
  formDescription.value = btn.description
  formBgColor.value = btn.bg_color
  formTextColor.value = btn.text_color
  formBorderRadius.value = btn.border_radius
  formWidth.value = btn.width
  formAlignment.value = btn.alignment
  formTarget.value = (btn.target as '_blank' | '_self') || '_blank'
  saveError.value = null

  // The button persists its own product link (product_provider/product_id)
  // since PR #72 -- restore it directly. Older buttons saved before that
  // fall back to the legacy guesswork below (target_url matched against
  // live product lists, mapping-name lookup for Ko-fi), which races the
  // async product loads and is why "Link to a product" kept showing as off.
  const PROVIDERS = ['polar', 'lemonsqueezy', 'paypal', 'gumroad', 'paddle', 'kofi', 'creem', 'patreon'] as const
  const persisted = btn.product_id && (PROVIDERS as readonly string[]).includes(btn.product_provider)
  const matchingPolar = polarProducts.value.find(p => p.checkout_url && p.checkout_url === btn.target_url)
  const matchingLs = lsProducts.value.find(p => p.checkout_url && p.checkout_url === btn.target_url)
  const matchingGumroad = gumroadProducts.value.find(p => p.checkout_url && p.checkout_url === btn.target_url)
  const matchingProduct = matchingPolar ?? matchingLs ?? matchingGumroad
  const kofiMapping = mappings.value.find(m => m.payment_provider === 'kofi' && m.metadata?.source_type === 'button' && m.metadata?.source_name === btn.name)
  if (persisted) {
    useProduct.value = true
    selectedProvider.value = btn.product_provider as typeof PROVIDERS[number]
    selectedProductId.value = btn.product_id
    syncMappingState(btn.product_id)
    nextTick(() => { formTargetUrl.value = btn.target_url })
  } else if (matchingProduct) {
    useProduct.value = true
    selectedProvider.value = matchingPolar ? 'polar' : matchingLs ? 'lemonsqueezy' : 'gumroad'
    selectedProductId.value = matchingProduct.id
    syncMappingState(matchingProduct.id)
    nextTick(() => { formTargetUrl.value = btn.target_url })
  } else if (kofiMapping) {
    useProduct.value = true
    selectedProvider.value = 'kofi'
    selectedProductId.value = kofiMapping.external_product_id
    syncMappingState(kofiMapping.external_product_id)
    nextTick(() => { formTargetUrl.value = btn.target_url })
  } else {
    useProduct.value = false
    selectedProductId.value = ''
    existingMappingId.value = null
    mappingEventType.value = 'order.paid'
    mappingGhostSubscribed.value = true
    mappingEmailType.value = 'signin'
    formTargetUrl.value = btn.target_url
  }

  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  if (!session.activeTenantSlug || !session.idToken) return
  if (!formName.value.trim()) return
  saving.value = true
  saveError.value = null
  const payload = {
    name: formName.value.trim(),
    label: formLabel.value || 'Buy now',
    description: formDescription.value,
    target_url: formTargetUrl.value,
    target: formTarget.value,
    bg_color: formBgColor.value,
    text_color: formTextColor.value,
    border_radius: formBorderRadius.value,
    width: formWidth.value,
    alignment: formAlignment.value,
    product_provider: useProduct.value && selectedProductId.value ? selectedProvider.value : '',
    product_id: useProduct.value ? selectedProductId.value : '',
  }
  try {
    if (editingId.value) {
      const updated = await updateBuyButton(session.activeTenantSlug, session.idToken, editingId.value, payload)
      buttons.value = buttons.value.map(b => b.id === updated.id ? updated : b)
    } else {
      const created = await createBuyButton(session.activeTenantSlug, session.idToken, payload)
      buttons.value.unshift(created)
      editingId.value = created.id
    }
    if (useProduct.value && selectedProductId.value) {
      const emailTypes = mappingEmailType.value ? [mappingEmailType.value as 'signin' | 'signup' | 'subscribe'] : []
      const mappingPayload = {
        payment_provider: selectedProvider.value,
        event_type: mappingEventType.value,
        external_product_id: selectedProductId.value,
        entitlement_key: 'button',
        action: 'grant' as const,
        quantity: 1,
        is_active: true,
        metadata: { ghost_subscribed: mappingGhostSubscribed.value, ghost_email_types: emailTypes, ghost_labels: [] as string[], source_type: 'button', source_name: formName.value.trim() },
      }
      try {
        if (existingMappingId.value !== null) {
          const updated = await updateMapping(session.activeTenantSlug, session.idToken, existingMappingId.value, mappingPayload)
          mappings.value = mappings.value.map(m => m.id === existingMappingId.value ? updated : m)
        } else {
          const created = await createMapping(session.activeTenantSlug, session.idToken, mappingPayload)
          existingMappingId.value = created.id
          mappings.value = [created, ...mappings.value]
        }
      } catch { /* mapping save non-fatal */ }
    }
    saveSuccess.value = true
    setTimeout(() => { saveSuccess.value = false }, 2500)
    saveError.value = null
    saveErrorPlan.value = null
  } catch (e: unknown) {
    saveError.value = e instanceof Error ? e.message : 'Save failed.'
    saveErrorPlan.value = isPlanLimitError(e) ? planKeyFromError(e) : null
  } finally {
    saving.value = false
  }
}

async function remove(btn: BuyButtonData) {
  if (!session.activeTenantSlug || !session.idToken) return
  if (!confirm(`Delete "${btn.name}"?`)) return
  await deleteBuyButton(session.activeTenantSlug, session.idToken, btn.id)
  buttons.value = buttons.value.filter(b => b.id !== btn.id)
  if (editingId.value === btn.id) resetForm()
}

function embedSnippet(btn: BuyButtonData) {
  return `<script src="https://api.payglue.io/button.js" data-id="${btn.id}"><\/script>`
}

async function copyRowSnippet(btn: BuyButtonData) {
  await navigator.clipboard.writeText(embedSnippet(btn))
  copiedRowId.value = btn.id
  setTimeout(() => { copiedRowId.value = null }, 2000)
}

const embedConfig = computed(() => {
  if (isEditing.value && editingId.value) return buttons.value.find(b => b.id === editingId.value) ?? null
  return null
})

const copyEmbedCode = async () => {
  if (!embedConfig.value) return
  await navigator.clipboard.writeText(embedSnippet(embedConfig.value))
  copiedEmbed.value = true
  setTimeout(() => { copiedEmbed.value = false }, 2000)
}

watch(selectedProductId, (id) => { if (id) syncMappingState(id) })

onMounted(() => { loadButtons(); loadPolarProducts(); loadLsProducts(); loadPayPalProducts(); loadGumroadProducts(); loadPaddleProducts(); loadCreemProducts(); loadPatreonProducts(); loadMappings() })
watch(() => session.activeTenantSlug, () => { loadButtons(); loadPolarProducts(); loadLsProducts(); loadPayPalProducts(); loadGumroadProducts(); loadPaddleProducts(); loadCreemProducts(); loadPatreonProducts(); loadMappings() })

// Patreon only grants on an active pledge (subscription.active); there is no
// one-off "order.paid" for a membership. Default the event type accordingly
// when Patreon is picked so the mapping matches the webhook.
watch(selectedProvider, (p) => { if (p === 'patreon') mappingEventType.value = 'subscription.active' })
</script>

<template>
  <AppShell>
    <div class="space-y-5">

      <PageHeader title="Buy Buttons" description="One script tag per button. Paste it anywhere, then update the label, color, or link here and it changes everywhere instantly, no HTML to touch." />

      <!-- Value prop -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 dark:border-slate-800 dark:bg-slate-800/40">
        <p class="mb-1.5 text-sm font-semibold text-slate-700 dark:text-slate-200">Why not use the button from Polar, Lemon Squeezy, or PayPal?</p>
        <p class="text-sm leading-relaxed text-slate-500 dark:text-slate-400">You can, but each platform gives you a different button with different settings. If you sell through multiple providers, or want to change button text or color, you have to log into each platform separately and update the HTML on every page. PayGlue buttons are provider-agnostic: create them once here, embed a single script tag, and manage everything from one place.</p>
      </section>

      <div class="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">

        <!-- Form -->
        <section
          class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 space-y-5"
          :class="isEditing ? 'ring-2 ring-indigo-400' : ''"
        >
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {{ isEditing ? 'Edit button' : 'New button' }}
            </h2>
            <button v-if="isEditing" type="button"
              class="flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-800 px-2.5 py-1 text-xs font-medium text-slate-500 dark:text-slate-400 hover:border-indigo-300 hover:text-indigo-600"
              @click="resetForm">
              <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              New button
            </button>
          </div>

          <!-- Internal name -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Name <span class="text-red-500 dark:text-rose-400">*</span> <span class="text-slate-400 dark:text-slate-500">(for your reference)</span></label>
            <input v-model="formName" type="text" placeholder="e.g. Buy me a coffee"
              class="w-full rounded-lg border px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none"
              :class="formName.trim() ? 'border-slate-200 dark:border-slate-800 focus:border-indigo-400' : 'border-red-300 focus:border-red-400'" />
            <p v-if="!formName.trim()" class="mt-1 text-xs text-red-500 dark:text-rose-400">Required</p>
          </div>

          <!-- Button label -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Button text</label>
            <input v-model="formLabel" type="text" placeholder="Buy now"
              class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Description -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Description <span class="text-slate-400 dark:text-slate-500">(optional, shown below button)</span></label>
            <input v-model="formDescription" type="text" placeholder="e.g. Support my work with a one-time coffee"
              class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Product toggle -->
          <div class="rounded-lg border p-4 space-y-3 transition-colors"
            :class="useProduct ? 'border-indigo-200 dark:border-indigo-500/30 bg-indigo-50/50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800'">
            <div class="flex items-center justify-between">
              <div>
                <p class="text-sm font-medium" :class="useProduct ? 'text-indigo-800 dark:text-indigo-300' : 'text-slate-800 dark:text-slate-100'">Link to a product?</p>
                <p class="text-xs mt-0.5" :class="useProduct ? 'text-indigo-500' : 'text-slate-500 dark:text-slate-400'">Turn off to use a custom URL (newsletter, event, etc.)</p>
              </div>
              <button type="button"
                class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none"
                :class="useProduct ? 'bg-indigo-600' : 'bg-slate-200'"
                @click="toggleUseProduct">
                <span class="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
                  :class="useProduct ? 'translate-x-5' : 'translate-x-0'" />
              </button>
            </div>
            <div v-if="useProduct" class="space-y-2">
              <div class="flex flex-wrap gap-1.5">
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'polar' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'polar'; selectedProductId = ''">Polar</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'lemonsqueezy' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'lemonsqueezy'; selectedProductId = ''">Lemon Squeezy</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'paypal' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'paypal'; selectedProductId = ''">PayPal</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'gumroad' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'gumroad'; selectedProductId = ''">Gumroad</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'paddle' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'paddle'; selectedProductId = ''">Paddle</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'kofi' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'kofi'; selectedProductId = ''; formTargetUrl = ''">Ko-fi</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'creem' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'creem'; selectedProductId = ''">Creem</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-colors"
                  :class="selectedProvider === 'patreon' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'"
                  @click="selectedProvider = 'patreon'; selectedProductId = ''">Patreon</button>
              </div>
              <template v-if="isManualProduct">
                <input v-model="selectedProductId" type="text" placeholder="Paste a shop item link (ko-fi.com/s/...), a tier name, or kofi-support"
                  class="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
                <p class="text-xs text-slate-400 dark:text-slate-500">For shop items, just paste the item's share link (Share &rarr; Copy link, e.g. <code>ko-fi.com/s/c0e30e5fcf</code>), we extract the item code and fill the button URL for you. For memberships, type the exact tier name as it appears on your Ko-fi page. Use <code>kofi-support</code> for plain tips.</p>
              </template>
              <template v-else>
                <p v-if="productsLoading" class="text-xs text-slate-400 dark:text-slate-500">Loading products...</p>
                <p v-else-if="productsError" class="text-xs text-amber-600 dark:text-amber-400">{{ productsError }}</p>
                <select v-else v-model="selectedProductId"
                  class="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                  <option value="">Select a product</option>
                  <option v-for="p in activeProducts" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
              </template>
              <p v-if="polarSandbox && selectedProvider === 'polar'" class="text-xs text-amber-600 dark:text-amber-400">Sandbox mode, using test products</p>
              <p v-if="selectedProvider === 'paypal'" class="text-xs text-slate-400 dark:text-slate-500">PayPal subscription plans do not have a direct checkout URL. Enter your PayPal checkout link manually in the URL field below after selecting a plan.</p>
              <p v-else-if="selectedProvider === 'paddle'" class="text-xs text-slate-400 dark:text-slate-500">Paddle checkout is driven client-side and has no direct checkout link. Enter your Paddle checkout link manually in the URL field below after selecting a product.</p>
              <p v-else-if="selectedProvider === 'patreon'" class="text-xs text-slate-400 dark:text-slate-500">Patreon has no per-tier checkout link. Patrons join through your Patreon page, so turn off "Link to a product" and paste your Patreon join URL in the field below. Access is still granted automatically by the tier mapping when someone pledges.</p>
              <p v-else-if="!isManualProduct && selectedProductId && !checkoutUrlForProduct(selectedProductId)" class="text-xs text-red-600">
                No checkout link available for this product.
                <template v-if="selectedProvider === 'polar'"> Check your Polar token scopes (needs <code>checkout_links:write</code>).</template>
              </p>
            </div>
          </div>

          <!-- Ghost actions mapping -->
          <div v-if="useProduct && selectedProductId" class="rounded-lg border border-indigo-100 dark:border-indigo-500/30 bg-indigo-50/40 dark:bg-indigo-500/10 p-4 space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Ghost actions</p>
              <span v-if="existingMappingId !== null" class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                <svg class="h-2.5 w-2.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                Mapped
              </span>
              <span v-else class="inline-flex items-center rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:text-slate-400">Not mapped</span>
            </div>
            <!-- Trigger event -->
            <div class="space-y-1.5">
              <p class="text-xs font-medium text-slate-600 dark:text-slate-300">Trigger event</p>
              <div class="grid grid-cols-2 gap-1.5">
                <button type="button"
                  class="flex items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors"
                  :class="mappingEventType === 'order.paid' ? 'border-indigo-300 bg-white dark:border-indigo-500/50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 bg-white/60 hover:bg-white dark:bg-slate-800/40 dark:hover:bg-slate-800'"
                  @click="mappingEventType = 'order.paid'">
                  <div>
                    <p class="text-xs font-medium text-slate-800 dark:text-slate-100">One-time</p>
                    <p class="text-[10px] text-slate-500 dark:text-slate-400">Lifetime, PWYW</p>
                  </div>
                  <div class="h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ml-2"
                    :class="mappingEventType === 'order.paid' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300 dark:border-slate-700'">
                    <div v-if="mappingEventType === 'order.paid'" class="h-1.5 w-1.5 rounded-full bg-white" />
                  </div>
                </button>
                <button type="button"
                  class="flex items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors"
                  :class="mappingEventType === 'subscription.active' ? 'border-indigo-300 bg-white dark:border-indigo-500/50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-800 bg-white/60 hover:bg-white dark:bg-slate-800/40 dark:hover:bg-slate-800'"
                  @click="mappingEventType = 'subscription.active'">
                  <div>
                    <p class="text-xs font-medium text-slate-800 dark:text-slate-100">Subscription</p>
                    <p class="text-[10px] text-slate-500 dark:text-slate-400">Monthly, annual</p>
                  </div>
                  <div class="h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ml-2"
                    :class="mappingEventType === 'subscription.active' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300 dark:border-slate-700'">
                    <div v-if="mappingEventType === 'subscription.active'" class="h-1.5 w-1.5 rounded-full bg-white" />
                  </div>
                </button>
              </div>
            </div>
            <!-- Newsletter -->
            <div class="flex items-center justify-between rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-3 py-2.5">
              <div>
                <p class="text-xs font-medium text-slate-800 dark:text-slate-100">Subscribe to newsletter</p>
                <p class="text-[10px] text-slate-500 dark:text-slate-400">Opt member into Ghost newsletter</p>
              </div>
              <div class="flex gap-3">
                <label class="flex items-center gap-1 cursor-pointer text-xs text-slate-700 dark:text-slate-200">
                  <input type="radio" :value="true" v-model="mappingGhostSubscribed" class="accent-indigo-600" /> Yes
                </label>
                <label class="flex items-center gap-1 cursor-pointer text-xs text-slate-700 dark:text-slate-200">
                  <input type="radio" :value="false" v-model="mappingGhostSubscribed" class="accent-indigo-600" /> No
                </label>
              </div>
            </div>
            <!-- Welcome email -->
            <div class="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 px-3 py-2.5">
              <p class="text-xs font-medium text-slate-800 dark:text-slate-100 mb-1.5">Welcome email</p>
              <select v-model="mappingEmailType" class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-xs text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                <option value="signin">Magic Link (recommended)</option>
                <option value="signup">Account confirmation</option>
                <option value="subscribe">Newsletter opt-in</option>
                <option value="">No email</option>
              </select>
            </div>
            <p class="text-[10px] text-slate-400 dark:text-slate-500">Saved automatically when you save this button.</p>
          </div>

          <!-- Link URL -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">
              Link URL
              <span v-if="useProduct && selectedProductId && !isManualProduct" class="ml-1 text-indigo-500">(auto-filled from product)</span>
              <span v-else-if="useProduct && isManualProduct" class="ml-1 text-slate-400 dark:text-slate-500">(paste your Ko-fi page URL)</span>
              <span v-else-if="!useProduct" class="ml-1 text-slate-400 dark:text-slate-500">(custom link)</span>
            </label>
            <input v-model="formTargetUrl" type="url"
              :placeholder="isManualProduct ? 'https://ko-fi.com/yourname' : useProduct ? 'Select a product above' : 'https://example.com/checkout'"
              class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Colors -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Button color</label>
              <div class="flex items-center gap-2">
                <input v-model="formBgColor" type="color" class="h-9 w-12 cursor-pointer rounded-lg border border-slate-200 dark:border-slate-800 p-0.5" />
                <input v-model="formBgColor" type="text" placeholder="#4f46e5"
                  class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm font-mono text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Text color</label>
              <div class="flex items-center gap-2">
                <input v-model="formTextColor" type="color" class="h-9 w-12 cursor-pointer rounded-lg border border-slate-200 dark:border-slate-800 p-0.5" />
                <input v-model="formTextColor" type="text" placeholder="#ffffff"
                  class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm font-mono text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none" />
              </div>
            </div>
          </div>

          <!-- Shape, Width, Alignment -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Corners</label>
              <select v-model="formBorderRadius" class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                <option value="none">Square</option>
                <option value="md">Rounded</option>
                <option value="full">Pill</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Width</label>
              <select v-model="formWidth" class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                <option value="auto">Auto</option>
                <option value="full">Full</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Align</label>
              <select v-model="formAlignment" class="w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none">
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </div>
          </div>

          <!-- Link target -->
          <div class="flex items-center justify-between rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40 px-3 py-2.5">
            <label class="text-xs font-medium text-slate-600 dark:text-slate-300">Open link in</label>
            <div class="flex gap-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-0.5">
              <button type="button"
                class="rounded px-3 py-1 text-xs font-medium transition-colors"
                :class="formTarget === '_blank' ? 'bg-indigo-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:text-slate-100'"
                @click="formTarget = '_blank'">New tab</button>
              <button type="button"
                class="rounded px-3 py-1 text-xs font-medium transition-colors"
                :class="formTarget === '_self' ? 'bg-indigo-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:text-slate-100'"
                @click="formTarget = '_self'">Same tab</button>
            </div>
          </div>

          <!-- Save error -->
          <UpgradeBanner v-if="saveError && saveErrorPlan" :message="saveError" :plan-key="saveErrorPlan" />
          <div v-else-if="saveError" class="rounded-lg border border-red-200 dark:border-rose-500/30 bg-red-50 dark:bg-rose-500/10 p-3 text-xs text-red-700 dark:text-rose-300">
            {{ saveError }}
          </div>

          <!-- Save -->
          <div class="flex items-center justify-end pt-1">
            <button type="button" :disabled="saving || !formName.trim()"
              class="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              :class="saveSuccess ? 'bg-emerald-600' : saving ? 'bg-slate-400' : 'bg-indigo-600 hover:bg-indigo-700'"
              @click="save">
              <svg v-if="saveSuccess" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <svg v-else-if="!saving" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M17 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V7l-4-4z" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M17 3v4H7V3" />
              </svg>
              <svg v-else class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              {{ saveSuccess ? 'Saved!' : saving ? 'Saving...' : isEditing ? 'Save changes' : 'Save' }}
            </button>
          </div>
        </section>

        <!-- Right column -->
        <div class="space-y-6">

          <!-- Preview -->
          <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-4">Preview</h2>
            <div class="rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40 p-6">
              <div :style="{ display: 'flex', justifyContent: formAlignment === 'center' ? 'center' : formAlignment === 'right' ? 'flex-end' : 'flex-start' }">
                <div>
                  <span :style="previewStyle">{{ formLabel || 'Buy now' }}</span>
                  <p v-if="formDescription" class="mt-1.5 text-xs text-slate-500 dark:text-slate-400" :style="{ textAlign: formAlignment }">{{ formDescription }}</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Embed code -- shown while in edit mode -->
          <section v-if="embedConfig" class="rounded-xl border-2 border-emerald-300 bg-emerald-50 dark:bg-emerald-500/10 p-5 shadow-sm space-y-4">
            <div class="flex items-center gap-2.5">
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-[11px] font-bold text-white">2</span>
              <h2 class="text-sm font-semibold text-emerald-900">Embed code</h2>
            </div>
            <p class="text-xs text-emerald-700 dark:text-emerald-300">Paste this script tag anywhere in your HTML. The button renders exactly where you place it.</p>
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <p class="text-xs font-medium text-emerald-800 dark:text-emerald-300">Script tag for {{ embedConfig.name }}</p>
                <button type="button"
                  class="flex items-center gap-1 rounded border border-emerald-300 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100"
                  @click="copyEmbedCode">
                  <svg v-if="!copiedEmbed" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <svg v-else class="h-3 w-3 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                  {{ copiedEmbed ? 'Copied' : 'Copy' }}
                </button>
              </div>
              <pre class="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ embedSnippet(embedConfig) }}</code></pre>
            </div>
          </section>

        </div>
      </div>

      <!-- Saved buttons list -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 px-5 py-4">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Saved buttons</h2>
            <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Click Edit to get the embed code again or update the button. Changes apply everywhere the button is embedded.</p>
          </div>
          <span class="rounded-full bg-slate-100 dark:bg-slate-800 px-2.5 py-0.5 text-xs font-medium text-slate-600 dark:text-slate-300">{{ buttons.length }}</span>
        </div>

        <div v-if="loading" class="px-5 py-8 text-center text-sm text-slate-400 dark:text-slate-500">Loading...</div>
        <div v-else-if="buttons.length === 0" class="px-5 py-10 text-center text-sm text-slate-400 dark:text-slate-500">
          No buttons yet. Create your first one above.
        </div>

        <ul v-else class="divide-y divide-slate-100">
          <li v-for="btn in buttons" :key="btn.id"
            class="flex items-start gap-4 px-5 py-4"
            :class="editingId === btn.id ? 'bg-indigo-50 dark:bg-indigo-500/10' : ''">

            <div class="mt-0.5 h-3 w-3 shrink-0 rounded-full ring-1 ring-slate-200 dark:ring-slate-700"
              :style="{ backgroundColor: btn.bg_color }" />

            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{{ btn.name }}</p>
              <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                {{ btn.label }}
                <span v-if="btn.target_url" class="text-slate-400 dark:text-slate-500">&middot; {{ btn.target_url }}</span>
              </p>
            </div>

            <div class="flex shrink-0 items-center gap-2 mt-0.5">
              <button type="button"
                class="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-800 px-2 py-1 text-[11px] font-medium text-slate-500 dark:text-slate-400 hover:border-indigo-300 hover:text-indigo-700"
                @click="copyRowSnippet(btn)">
                <svg v-if="copiedRowId !== btn.id" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <svg v-else class="h-3 w-3 text-emerald-500" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
                {{ copiedRowId === btn.id ? 'Copied' : 'Copy' }}
              </button>
              <button type="button"
                class="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-800 px-2 py-1 text-[11px] font-medium text-slate-500 dark:text-slate-400 hover:border-amber-300 hover:text-amber-600"
                @click="startEdit(btn)">
                <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                Edit
              </button>
              <button type="button"
                class="flex items-center rounded border border-slate-200 dark:border-slate-800 p-1 text-slate-400 dark:text-slate-500 hover:border-red-200 hover:text-red-500"
                @click="remove(btn)">
                <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </li>
        </ul>
      </section>

    </div>
  </AppShell>
</template>
