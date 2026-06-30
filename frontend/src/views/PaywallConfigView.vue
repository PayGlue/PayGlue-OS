// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { useSessionStore } from '../stores/session'
import {
  getPolarProducts,
  getLemonSqueezyProducts,
  getPayPalProducts,
  listPaywallConfigs,
  createPaywallConfig,
  updatePaywallConfig,
  deletePaywallConfig,
  listPricingTables,
  listMappings,
  createMapping,
  updateMapping,
  type PaywallConfigData,
} from '../lib/api'
import type { ProductMapping } from '../types/api'
import { useHeaderScriptStatus } from '../composables/useHeaderScriptStatus'

const session = useSessionStore()
const { isInstalled: headerScriptInstalled } = useHeaderScriptStatus()

interface Product { id: string; name: string; checkout_url?: string }

const selectedProvider = ref<'polar' | 'lemonsqueezy' | 'paypal'>('polar')

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

const activeProducts = computed(() => {
  if (selectedProvider.value === 'polar') return polarProducts.value
  if (selectedProvider.value === 'paypal') return paypalProducts.value
  return lsProducts.value
})
const productsLoading = computed(() => {
  if (selectedProvider.value === 'polar') return polarProductsLoading.value
  if (selectedProvider.value === 'paypal') return paypalProductsLoading.value
  return lsProductsLoading.value
})
const productsError = computed(() => {
  if (selectedProvider.value === 'polar') return polarProductsError.value
  if (selectedProvider.value === 'paypal') return paypalProductsError.value
  return lsProductsError.value
})

const savedConfigs = ref<PaywallConfigData[]>([])
const configsLoading = ref(false)

const editingId = ref<string | null>(null)
const ctaMode = ref<'product' | 'pricing_table' | 'custom'>('product')
const formName = ref('')
const selectedProductId = ref('')
const selectedTableId = ref('')
const pricingTables = ref<{ id: string; name: string }[]>([])
const tablesLoading = ref(false)
const headline = ref('Premium content')
const body = ref('Purchase access to continue reading.')
const buttonText = ref('Get access')
const buttonUrl = ref('')
const buttonColor = ref('#4f46e5')
const textColor = ref('#ffffff')
const borderRadius = ref<'none' | 'md' | 'full'>('md')
const formWidth = ref<'auto' | 'full'>('auto')
const formAlignment = ref<'left' | 'center' | 'right'>('left')

const mappings = ref<ProductMapping[]>([])
const existingMappingId = ref<number | null>(null)
const mappingEventType = ref<'order.paid' | 'subscription.active'>('order.paid')
const mappingGhostSubscribed = ref(true)
const mappingEmailType = ref<'signin' | 'signup' | 'subscribe' | ''>('signin')

const saving = ref(false)
const saveError = ref<string | null>(null)
const copiedRowId = ref<string | null>(null)
const justSavedConfig = ref<PaywallConfigData | null>(null)
const copiedStep2 = ref(false)

const isEditing = computed(() => editingId.value !== null)

function buildSnippet(cfg: { product_id?: string; headline: string; body: string; button_text: string; button_url: string; button_color: string; id?: string }) {
  const lines: string[] = []
  if (cfg.id) {
    lines.push(`  data-paywall-id="${cfg.id}"`)
  } else if (cfg.product_id) {
    lines.push(`  data-product-id="${cfg.product_id}"`)
  }
  return `<!-- Everything above this line is visible to everyone. Content below is hidden behind the paywall. -->\n<div data-payglue-gated\n${lines.join('\n')}></div>`
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

async function loadMappings() {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  try {
    mappings.value = await listMappings(slug, token)
  } catch { /* non-fatal */ }
}

function resetForm() {
  editingId.value = null
  formName.value = ''
  selectedProductId.value = ''
  selectedTableId.value = ''
  ctaMode.value = 'product'
  headline.value = 'Premium content'
  body.value = 'Purchase access to continue reading.'
  buttonText.value = 'Get access'
  buttonUrl.value = ''
  buttonColor.value = '#4f46e5'
  textColor.value = '#ffffff'
  borderRadius.value = 'md'
  formWidth.value = 'auto'
  formAlignment.value = 'left'
  existingMappingId.value = null
  mappingEventType.value = 'order.paid'
  mappingGhostSubscribed.value = true
  mappingEmailType.value = 'signin'
}

function startEdit(cfg: PaywallConfigData) {
  justSavedConfig.value = null
  editingId.value = cfg.id
  formName.value = cfg.name
  headline.value = cfg.headline
  body.value = cfg.body
  buttonText.value = cfg.button_text
  buttonColor.value = cfg.button_color
  textColor.value = cfg.text_color || '#ffffff'
  borderRadius.value = cfg.border_radius || 'md'
  formWidth.value = cfg.width || 'auto'
  formAlignment.value = cfg.alignment || 'left'
  if (cfg.button_url?.startsWith('payglue-table:')) {
    ctaMode.value = 'pricing_table'
    selectedTableId.value = cfg.button_url.replace('payglue-table:', '')
    nextTick(() => { buttonUrl.value = cfg.button_url })
  } else if (cfg.product_id) {
    ctaMode.value = 'product'
    selectedProductId.value = cfg.product_id
    if (lsProducts.value.some(p => p.id === cfg.product_id)) selectedProvider.value = 'lemonsqueezy'
    else if (paypalProducts.value.some(p => p.id === cfg.product_id)) selectedProvider.value = 'paypal'
    else selectedProvider.value = 'polar'
    syncMappingState(cfg.product_id)
    nextTick(() => { buttonUrl.value = cfg.button_url })
  } else {
    ctaMode.value = 'custom'
    nextTick(() => { buttonUrl.value = cfg.button_url })
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function saveConfig() {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  if (!formName.value.trim()) return
  saving.value = true
  saveError.value = null
  const product = activeProducts.value.find(p => p.id === selectedProductId.value)
  const payload = {
    name: formName.value.trim() || 'Untitled paywall',
    product_id: ctaMode.value === 'product' ? selectedProductId.value : '',
    product_name: ctaMode.value === 'product' ? (product?.name ?? selectedProductId.value) : (ctaMode.value === 'pricing_table' ? (pricingTables.value.find(t => t.id === selectedTableId.value)?.name ?? 'Pricing Table') : 'Custom URL'),
    headline: headline.value || 'Premium content',
    body: body.value || 'Purchase access to continue reading.',
    button_text: buttonText.value || 'Get access',
    button_url: buttonUrl.value,
    button_color: buttonColor.value,
    text_color: textColor.value,
    border_radius: borderRadius.value,
    width: formWidth.value,
    alignment: formAlignment.value,
  }
  try {
    if (isEditing.value && editingId.value) {
      const updated = await updatePaywallConfig(slug, token, editingId.value, payload)
      savedConfigs.value = savedConfigs.value.map(c => c.id === updated.id ? updated : c)
    } else {
      const created = await createPaywallConfig(slug, token, payload)
      savedConfigs.value.unshift(created)
      justSavedConfig.value = created
    }
    if (ctaMode.value === 'product' && selectedProductId.value) {
      const emailTypes = mappingEmailType.value ? [mappingEmailType.value as 'signin' | 'signup' | 'subscribe'] : []
      const mappingPayload = {
        payment_provider: selectedProvider.value,
        event_type: mappingEventType.value,
        external_product_id: selectedProductId.value,
        entitlement_key: 'paywall',
        action: 'grant' as const,
        quantity: 1,
        is_active: true,
        metadata: { ghost_subscribed: mappingGhostSubscribed.value, ghost_email_types: emailTypes, ghost_labels: [] as string[], source_type: 'paywall', source_name: formName.value.trim() },
      }
      try {
        if (existingMappingId.value !== null) {
          const updated = await updateMapping(slug, token, existingMappingId.value, mappingPayload)
          mappings.value = mappings.value.map(m => m.id === existingMappingId.value ? updated : m)
        } else {
          const created = await createMapping(slug, token, mappingPayload)
          existingMappingId.value = created.id
          mappings.value = [created, ...mappings.value]
        }
      } catch { /* mapping save non-fatal */ }
    }
    if (isEditing.value) justSavedConfig.value = null
    resetForm()
  } catch (err: unknown) {
    saveError.value = err instanceof Error ? err.message : 'Could not save. Check the console for details.'
  } finally {
    saving.value = false
  }
}

async function removeConfig(id: string) {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  await deletePaywallConfig(slug, token, id)
  savedConfigs.value = savedConfigs.value.filter(c => c.id !== id)
  if (editingId.value === id) resetForm()
}

async function loadConfigs() {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  configsLoading.value = true
  try {
    savedConfigs.value = await listPaywallConfigs(slug, token)
  } finally {
    configsLoading.value = false
  }
}

async function loadPolarProducts() {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  polarProductsLoading.value = true
  polarProductsError.value = null
  try {
    const result = await getPolarProducts(slug, token)
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
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  lsProductsLoading.value = true
  lsProductsError.value = null
  try {
    const result = await getLemonSqueezyProducts(slug, token)
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
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  paypalProductsLoading.value = true
  paypalProductsError.value = null
  try {
    const result = await getPayPalProducts(slug, token)
    paypalProducts.value = result.products ?? []
    if (!result.has_token) paypalProductsError.value = 'No PayPal credentials configured. Connect PayPal first.'
    else if (result.error) paypalProductsError.value = result.error
  } catch {
    paypalProductsError.value = 'Could not load PayPal plans.'
  } finally {
    paypalProductsLoading.value = false
  }
}

async function loadPricingTables() {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  tablesLoading.value = true
  try {
    const result = await listPricingTables(slug, token)
    pricingTables.value = result.map(t => ({ id: t.id, name: t.name }))
  } finally {
    tablesLoading.value = false
  }
}

watch(selectedProductId, (id) => { if (id && ctaMode.value === 'product') syncMappingState(id) })

onMounted(() => { loadConfigs(); loadPolarProducts(); loadLsProducts(); loadPayPalProducts(); loadPricingTables(); loadMappings() })
watch(() => session.activeTenantSlug, () => { loadConfigs(); loadPolarProducts(); loadLsProducts(); loadPayPalProducts(); loadPricingTables(); loadMappings() })

const checkoutUrlForProduct = (id: string) => {
  const p = activeProducts.value.find(p => p.id === id)
  return p?.checkout_url ?? ''
}

watch(selectedProductId, (id) => {
  if (ctaMode.value === 'product' && id) buttonUrl.value = checkoutUrlForProduct(id)
})
watch(selectedTableId, (id) => {
  if (ctaMode.value === 'pricing_table' && id) buttonUrl.value = 'payglue-table:' + id
})
watch(ctaMode, (val) => {
  if (val === 'product' && selectedProductId.value) buttonUrl.value = checkoutUrlForProduct(selectedProductId.value)
  else if (val === 'pricing_table' && selectedTableId.value) buttonUrl.value = 'payglue-table:' + selectedTableId.value
  else if (val === 'pricing_table' || val === 'product') buttonUrl.value = ''
})

const copyRowSnippet = async (cfg: PaywallConfigData) => {
  try {
    await navigator.clipboard.writeText(buildSnippet(cfg))
    copiedRowId.value = cfg.id; setTimeout(() => { copiedRowId.value = null }, 2000)
  } catch { /* clipboard unavailable */ }
}
const copyStep2 = async () => {
  if (!step2Config.value) return
  try {
    await navigator.clipboard.writeText(buildSnippet(step2Config.value))
    copiedStep2.value = true; setTimeout(() => { copiedStep2.value = false }, 2000)
  } catch { /* clipboard unavailable */ }
}

const step2Config = computed(() => {
  if (justSavedConfig.value) return justSavedConfig.value
  if (isEditing.value && editingId.value) return savedConfigs.value.find(c => c.id === editingId.value) ?? null
  return null
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <!-- Header -->
      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-amber-600">Paywall</p>
        <h1 class="mt-1 text-xl font-semibold text-slate-900">Paywall configuration</h1>
        <p class="mt-1 text-sm text-slate-600">
          Gate individual Ghost articles behind any payment provider — ideal if Stripe is not available in your country, or if you want to sell articles as one-time purchases via Polar, Lemon Squeezy, or any other provider of your choice. Configure a paywall per article and paste the snippet into your Ghost HTML card.
        </p>
      </section>

      <div class="grid gap-6 lg:grid-cols-2">

        <!-- Config form -->
        <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-5" :class="isEditing ? 'ring-2 ring-indigo-400' : ''">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {{ isEditing ? 'Edit paywall' : 'New paywall' }}
            </h2>
            <button v-if="isEditing" type="button" class="text-xs text-slate-400 hover:text-slate-700" @click="resetForm">
              Cancel
            </button>
          </div>

          <!-- Name -->
          <div>
            <label class="block text-xs font-medium text-slate-600 mb-1">Name <span class="text-red-500">*</span> <span class="text-slate-400">(for your reference)</span></label>
            <input v-model="formName" type="text" required placeholder="e.g. Barista Club — June article"
              class="w-full rounded-lg border px-3 py-2 text-sm text-slate-800 focus:outline-none"
              :class="formName.trim() ? 'border-slate-200 focus:border-indigo-400' : 'border-red-300 focus:border-red-400'" />
            <p v-if="!formName.trim()" class="mt-1 text-xs text-red-500">Required</p>
          </div>

          <!-- CTA mode selector -->
          <div class="rounded-lg border border-slate-200 p-4 space-y-3">
            <div>
              <p class="text-sm font-medium text-slate-800 mb-2">Button action</p>
              <div class="flex gap-1.5">
                <button type="button" @click="ctaMode = 'product'"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  :class="ctaMode === 'product' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'">
                  Product
                </button>
                <button type="button" @click="ctaMode = 'pricing_table'"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  :class="ctaMode === 'pricing_table' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'">
                  Pricing Table
                </button>
                <button type="button" @click="ctaMode = 'custom'"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  :class="ctaMode === 'custom' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'">
                  Custom URL
                </button>
              </div>
            </div>

            <!-- Product picker -->
            <div v-if="ctaMode === 'product'" class="space-y-2">
              <div class="flex gap-1.5">
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold transition-colors"
                  :class="selectedProvider === 'polar' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
                  @click="selectedProvider = 'polar'; selectedProductId = ''">Polar</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold transition-colors"
                  :class="selectedProvider === 'lemonsqueezy' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
                  @click="selectedProvider = 'lemonsqueezy'; selectedProductId = ''">Lemon Squeezy</button>
                <button type="button"
                  class="rounded-md px-3 py-1 text-xs font-semibold transition-colors"
                  :class="selectedProvider === 'paypal' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
                  @click="selectedProvider = 'paypal'; selectedProductId = ''">PayPal</button>
              </div>
              <p v-if="productsLoading" class="text-xs text-slate-400">Loading products...</p>
              <p v-else-if="productsError" class="text-xs text-amber-600">{{ productsError }}</p>
              <select v-else v-model="selectedProductId"
                class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="">Select a product</option>
                <option v-for="p in activeProducts" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select>
              <p v-if="polarSandbox && selectedProvider === 'polar'" class="text-xs text-amber-600">Sandbox mode — using test products</p>
            </div>

            <!-- Pricing table picker -->
            <div v-if="ctaMode === 'pricing_table'">
              <label class="block text-xs font-medium text-slate-600 mb-1">Pricing table</label>
              <p v-if="tablesLoading" class="text-xs text-slate-400">Loading tables...</p>
              <select v-else v-model="selectedTableId"
                class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="">Select a pricing table</option>
                <option v-for="t in pricingTables" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
              <p v-if="!tablesLoading && pricingTables.length === 0" class="mt-1 text-xs text-amber-600">No pricing tables found. Create one first in the Pricing Table section.</p>
              <p class="mt-1.5 text-xs text-slate-400">The paywall button will open the selected table in an overlay. Visitors can choose their own plan.</p>
            </div>
          </div>

          <!-- Ghost actions mapping (shown when product is linked) -->
          <div v-if="ctaMode === 'product' && selectedProductId" class="rounded-lg border border-indigo-100 bg-indigo-50/40 p-4 space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-xs font-semibold uppercase tracking-widest text-indigo-600">Ghost actions</p>
              <span v-if="existingMappingId !== null" class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                <svg class="h-2.5 w-2.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                Mapped
              </span>
              <span v-else class="inline-flex items-center rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-500">Not mapped</span>
            </div>
            <!-- Trigger event -->
            <div class="space-y-1.5">
              <p class="text-xs font-medium text-slate-600">Trigger event</p>
              <div class="grid grid-cols-2 gap-1.5">
                <button type="button"
                  class="flex items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors"
                  :class="mappingEventType === 'order.paid' ? 'border-indigo-300 bg-white' : 'border-slate-200 bg-white/60 hover:bg-white'"
                  @click="mappingEventType = 'order.paid'">
                  <div>
                    <p class="text-xs font-medium text-slate-800">One-time</p>
                    <p class="text-[10px] text-slate-500">Lifetime, PWYW</p>
                  </div>
                  <div class="h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ml-2"
                    :class="mappingEventType === 'order.paid' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300'">
                    <div v-if="mappingEventType === 'order.paid'" class="h-1.5 w-1.5 rounded-full bg-white" />
                  </div>
                </button>
                <button type="button"
                  class="flex items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors"
                  :class="mappingEventType === 'subscription.active' ? 'border-indigo-300 bg-white' : 'border-slate-200 bg-white/60 hover:bg-white'"
                  @click="mappingEventType = 'subscription.active'">
                  <div>
                    <p class="text-xs font-medium text-slate-800">Subscription</p>
                    <p class="text-[10px] text-slate-500">Monthly, annual</p>
                  </div>
                  <div class="h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ml-2"
                    :class="mappingEventType === 'subscription.active' ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300'">
                    <div v-if="mappingEventType === 'subscription.active'" class="h-1.5 w-1.5 rounded-full bg-white" />
                  </div>
                </button>
              </div>
            </div>
            <!-- Newsletter -->
            <div class="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2.5">
              <div>
                <p class="text-xs font-medium text-slate-800">Subscribe to newsletter</p>
                <p class="text-[10px] text-slate-500">Opt member into Ghost newsletter</p>
              </div>
              <div class="flex gap-3">
                <label class="flex items-center gap-1 cursor-pointer text-xs text-slate-700">
                  <input type="radio" :value="true" v-model="mappingGhostSubscribed" class="accent-indigo-600" /> Yes
                </label>
                <label class="flex items-center gap-1 cursor-pointer text-xs text-slate-700">
                  <input type="radio" :value="false" v-model="mappingGhostSubscribed" class="accent-indigo-600" /> No
                </label>
              </div>
            </div>
            <!-- Welcome email -->
            <div class="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
              <p class="text-xs font-medium text-slate-800 mb-1.5">Welcome email</p>
              <select v-model="mappingEmailType" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="signin">Magic Link (recommended)</option>
                <option value="signup">Account confirmation</option>
                <option value="subscribe">Newsletter opt-in</option>
                <option value="">No email</option>
              </select>
            </div>
            <p class="text-[10px] text-slate-400">Saved automatically when you save this paywall.</p>
          </div>

          <!-- Headline -->
          <div>
            <label class="block text-xs font-medium text-slate-600 mb-1">Headline</label>
            <input v-model="headline" type="text" placeholder="Premium content"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Body -->
          <div>
            <label class="block text-xs font-medium text-slate-600 mb-1">Body text</label>
            <textarea v-model="body" rows="2" placeholder="Purchase access to continue reading."
              class="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Button text -->
          <div>
            <label class="block text-xs font-medium text-slate-600 mb-1">Button text</label>
            <input v-model="buttonText" type="text" placeholder="Get access"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none" />
          </div>

          <!-- Button URL (hidden for pricing_table mode) -->
          <div v-if="ctaMode !== 'pricing_table'">
            <label class="block text-xs font-medium text-slate-600 mb-1">
              Button URL
              <span v-if="ctaMode === 'product' && selectedProductId" class="ml-1 text-indigo-500">(auto-filled from product)</span>
              <span v-else-if="ctaMode === 'custom'" class="ml-1 text-slate-400">(custom link)</span>
            </label>
            <input v-model="buttonUrl" type="url" :placeholder="ctaMode === 'product' ? 'Select a product above' : 'https://example.com/checkout'"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none" />
            <p v-if="polarSandbox" class="mt-1.5 text-xs text-amber-600">
              Polar sandbox connected. Sandbox checkout links only open when logged into Polar — this is a Polar sandbox limitation, not a PayGlue issue. Production checkout links work publicly without login.
            </p>
          </div>

          <!-- Colors -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">Button color</label>
              <div class="flex items-center gap-2">
                <input v-model="buttonColor" type="color" class="h-9 w-12 cursor-pointer rounded-lg border border-slate-200 p-0.5" />
                <input v-model="buttonColor" type="text" placeholder="#4f46e5"
                  class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono text-slate-800 focus:border-indigo-400 focus:outline-none" />
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">Text color</label>
              <div class="flex items-center gap-2">
                <input v-model="textColor" type="color" class="h-9 w-12 cursor-pointer rounded-lg border border-slate-200 p-0.5" />
                <input v-model="textColor" type="text" placeholder="#ffffff"
                  class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono text-slate-800 focus:border-indigo-400 focus:outline-none" />
              </div>
            </div>
          </div>

          <!-- Shape, Width, Alignment -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">Corners</label>
              <select v-model="borderRadius" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="none">Square</option>
                <option value="md">Rounded</option>
                <option value="full">Pill</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">Width</label>
              <select v-model="formWidth" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="auto">Auto</option>
                <option value="full">Full</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">Align</label>
              <select v-model="formAlignment" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </div>
          </div>

          <!-- Save error -->
          <div v-if="saveError" class="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            {{ saveError }}
          </div>

          <!-- Save -->
          <div class="flex items-center justify-end pt-1">
            <button type="button" :disabled="saving || !formName.trim()"
              class="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              :class="saving ? 'bg-slate-400' : 'bg-indigo-600 hover:bg-indigo-700'"
              @click="saveConfig">
              <svg v-if="!saving" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M17 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V7l-4-4z" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M17 3v4H7V3" />
              </svg>
              <svg v-else class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              {{ isEditing ? 'Save changes' : 'Save' }}
            </button>
          </div>
        </section>

        <!-- Right column -->
        <div class="space-y-6">

          <!-- Preview -->
          <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-4">Preview</h2>
            <div class="relative overflow-hidden rounded-lg border border-slate-100 bg-slate-50">
              <div class="space-y-2.5 p-6 opacity-25 select-none">
                <div class="h-4 w-1/2 rounded-full bg-slate-500 mb-4" />
                <div class="h-2.5 w-full rounded-full bg-slate-400" />
                <div class="h-2.5 w-5/6 rounded-full bg-slate-400" />
                <div class="h-2.5 w-full rounded-full bg-slate-400" />
                <div class="h-2.5 w-3/4 rounded-full bg-slate-400" />
                <div class="h-2.5 w-full rounded-full bg-slate-400" />
                <div class="h-2.5 w-4/5 rounded-full bg-slate-400" />
              </div>
              <div class="absolute inset-0 flex items-end justify-center pb-4 bg-gradient-to-b from-transparent via-white/60 to-white/95">
                <div class="mx-4 w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-lg">
                  <p class="text-base font-semibold text-slate-900">{{ headline || 'Premium content' }}</p>
                  <p class="mt-2 text-sm text-slate-500 leading-relaxed">{{ body || 'Purchase access to continue reading.' }}</p>
                  <div
                    class="mt-5 inline-block px-5 py-2.5 text-sm font-semibold"
                    :style="{
                      backgroundColor: buttonColor,
                      color: textColor,
                      borderRadius: borderRadius === 'full' ? '9999px' : borderRadius === 'none' ? '0' : '8px',
                      width: formWidth === 'full' ? '100%' : 'auto',
                      textAlign: formAlignment,
                      boxSizing: 'border-box',
                      display: formWidth === 'full' ? 'block' : 'inline-block',
                    }">{{ buttonText || 'Get access' }}</div>
                </div>
              </div>
            </div>
          </section>

          <!-- Step 1 — Header script status -->
          <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div class="flex items-center justify-between gap-4">
              <div class="flex items-center gap-3">
                <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
                  <svg class="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
                  </svg>
                </div>
                <div>
                  <p class="text-sm font-medium text-slate-800">Header script</p>
                  <p class="text-xs text-slate-500">Required once in Ghost Site Header</p>
                </div>
              </div>
              <div class="flex items-center gap-3">
                <span
                  v-if="headerScriptInstalled"
                  class="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200"
                >
                  <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                  Installed
                </span>
                <span
                  v-else
                  class="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
                >Not installed</span>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/installation`"
                  class="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline whitespace-nowrap"
                >
                  {{ headerScriptInstalled ? 'View setup' : 'Set up' }} &rarr;
                </RouterLink>
              </div>
            </div>
          </section>

          <!-- Step 2 — shown after saving or while editing -->
          <section v-if="step2Config" class="rounded-xl border-2 border-emerald-300 bg-emerald-50 p-5 shadow-sm space-y-4">
            <div class="flex items-center gap-2.5">
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-[11px] font-bold text-white">2</span>
              <h2 class="text-sm font-semibold text-emerald-900">
                {{ justSavedConfig ? 'Saved! Paste into your Ghost article' : 'Article snippet' }}
              </h2>
            </div>
            <p class="text-xs text-emerald-700">In Ghost, open the article, add an HTML card, and paste this snippet where you want the paywall to appear.</p>
            <div class="flex gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
              <svg class="mt-0.5 h-4 w-4 shrink-0 text-amber-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
              <p class="text-xs text-amber-800 leading-relaxed">
                <span class="font-semibold">Set the Ghost article to Public.</span>
                If the article is set to "Members only" or "Paid members only" in Ghost, Ghost overrides the paywall and blocks the article entirely before our snippet can run. The PayGlue paywall handles access control — Ghost must not restrict visibility on its own.
              </p>
            </div>
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <p class="text-xs font-medium text-emerald-800">HTML card snippet — {{ step2Config.name }}</p>
                <button type="button"
                  class="flex items-center gap-1 rounded border border-emerald-300 bg-white px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100"
                  @click="copyStep2">
                  <svg v-if="!copiedStep2" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <svg v-else class="h-3 w-3 text-emerald-600" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                  {{ copiedStep2 ? 'Copied' : 'Copy' }}
                </button>
              </div>
              <pre class="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ buildSnippet(step2Config) }}</code></pre>
            </div>
            <div class="rounded-lg border border-emerald-200 bg-white/60 p-3 text-xs text-emerald-700">
              Content <span class="font-semibold">above</span> this snippet in your Ghost article is visible to everyone. Content <span class="font-semibold">below</span> is hidden behind the paywall overlay.
            </div>
          </section>

        </div>
      </div>

      <!-- Saved configs list -->
      <section class="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 class="text-sm font-semibold text-slate-900">Saved paywalls</h2>
            <p class="text-xs text-slate-500 mt-0.5">Copy the snippet per article and paste into an HTML card in Ghost. Headline, body and button update automatically when you edit — no need to update Ghost.</p>
          </div>
          <span class="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">{{ savedConfigs.length }}</span>
        </div>

        <div v-if="configsLoading" class="px-5 py-8 text-center text-sm text-slate-400">Loading...</div>
        <div v-else-if="savedConfigs.length === 0" class="px-5 py-10 text-center text-sm text-slate-400">
          No paywalls saved yet. Configure one above and click "Save".
        </div>

        <ul v-else class="divide-y divide-slate-100">
          <li v-for="cfg in savedConfigs" :key="cfg.id"
            class="flex items-start gap-4 px-5 py-4"
            :class="editingId === cfg.id ? 'bg-indigo-50' : ''">

            <div class="mt-0.5 h-3 w-3 shrink-0 rounded-full ring-1 ring-slate-200"
              :style="{ backgroundColor: cfg.button_color || '#4f46e5' }" />

            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-slate-900 truncate">{{ cfg.name }}</p>
              <p class="text-xs text-slate-500 mt-0.5 truncate">
                {{ cfg.product_name || 'Custom URL' }}
                <span v-if="cfg.button_url" class="text-slate-400">&middot; {{ cfg.button_url }}</span>
              </p>
            </div>

            <div class="flex shrink-0 items-center gap-2 mt-0.5">
              <button type="button"
                class="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] font-medium text-slate-500 hover:border-indigo-300 hover:text-indigo-700"
                @click="copyRowSnippet(cfg)">
                <svg v-if="copiedRowId !== cfg.id" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <svg v-else class="h-3 w-3 text-emerald-500" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
                {{ copiedRowId === cfg.id ? 'Copied' : 'Copy' }}
              </button>
              <button type="button"
                class="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] font-medium text-slate-500 hover:border-amber-300 hover:text-amber-600"
                @click="startEdit(cfg)">
                <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                Edit
              </button>
              <button type="button"
                class="flex items-center rounded border border-slate-200 p-1 text-slate-400 hover:border-red-200 hover:text-red-500"
                @click="removeConfig(cfg.id)">
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
