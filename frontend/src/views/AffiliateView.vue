// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PLAN_TIERS } from '../lib/planUpgrade'
import { useFoundingTier } from '../composables/useFoundingTier'

// The first version of this page listed facts and invited nobody. A referral
// programme only works if somebody wants to share it, so this one leads with
// the offer and lets the numbers carry the argument.
//
// The affiliate programme itself runs on Creem: commissions are paid by
// whoever handles the money, and that is not us. That means a separate Creem
// account, which is stated on the page rather than discovered after the click.
const JOIN_URL = 'https://affiliates.creem.io/join/payglue'

const HEADLINE_STATS = [
  { value: '40', unit: '%', label: 'of every payment, for as long as they stay' },
  { value: '30', unit: ' days', label: 'cookie window after the click' },
  { value: '0', unit: ' €', label: 'to join, no minimum payout' },
]

const STEPS = [
  {
    step: 'Step 1',
    title: 'Grab your link',
    body: 'One link, yours forever. Put it in a post, a newsletter, or a reply to someone asking how you take payments.',
    tone: 'indigo',
    path: 'M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244',
  },
  {
    step: 'Step 2',
    title: 'They sign up',
    body: 'Anyone who clicks and buys within 30 days is yours, even if they wander off and come back later.',
    tone: 'violet',
    path: 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0z',
  },
  {
    step: 'Step 3',
    title: 'You get paid',
    body: 'Creem tracks it and pays out. The money does not depend on us remembering to send it.',
    tone: 'emerald',
    path: 'M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33',
  },
] as const

// Prices come from PLAN_TIERS, the same list the pricing page renders. The
// previous version of this page carried three hand-written figures that were
// roughly a quarter of the real commission -- wrong in the direction that
// undersells the programme, and impossible to notice because nothing tied them
// to an actual price.
const COMMISSION_RATE = 0.4

const { currentTierPrice } = useFoundingTier()

// Founding is first and preselected because it is the only plan anybody can
// buy right now -- Solo, Studio and Agency all read "available at public
// launch" on the pricing page. Offering only those three would quote a
// referral at 19 EUR when the real figure today is 9, which overstates the
// programme in exactly the way the hand-written numbers used to.
// Its price is read from the live ladder, so it follows the tier that is on
// sale rather than being pinned to 9.
const plans = computed(() => [
  { key: 'founding', name: 'Founding', monthly: currentTierPrice.value },
  ...PLAN_TIERS.map((tier) => ({ key: tier.key, name: tier.name, monthly: tier.monthly })),
])

const selectedPlanKey = ref('founding')
const referrals = ref(5)

const selectedPlan = computed(
  () => plans.value.find((p) => p.key === selectedPlanKey.value) ?? plans.value[0],
)

const perMonth = computed(
  () => selectedPlan.value.monthly * COMMISSION_RATE * referrals.value,
)
const perYear = computed(() => perMonth.value * 12)

/** Whole euros unless the half matters, which it does at one Solo referral. */
const money = (value: number) =>
  Number.isInteger(value) ? `${value} €` : `${value.toFixed(2).replace('.', ',')} €`

const TONES: Record<string, string> = {
  indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300',
  violet: 'bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300',
  emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300',
}
const STEP_LABEL: Record<string, string> = {
  indigo: 'text-indigo-500 dark:text-indigo-400',
  violet: 'text-violet-500 dark:text-violet-400',
  emerald: 'text-emerald-600 dark:text-emerald-400',
}
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <!-- Hero -->
      <section class="living-gradient rise relative overflow-hidden rounded-3xl px-8 py-12 text-white shadow-xl shadow-indigo-500/20 md:px-12 md:py-16">
        <div class="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-white/10 blur-2xl"></div>
        <div class="pointer-events-none absolute -bottom-24 -left-10 h-72 w-72 rounded-full bg-white/10 blur-3xl"></div>

        <div class="relative max-w-2xl">
          <span class="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold backdrop-blur">
            <span class="relative flex h-2 w-2">
              <span class="ring absolute inline-flex h-2 w-2"></span>
              <span class="relative inline-flex h-2 w-2 rounded-full bg-white"></span>
            </span>
            Open to every customer
          </span>

          <h1 class="mt-6 text-4xl font-bold leading-[1.05] tracking-tight md:text-5xl">
            Get paid for<br />word of mouth.
          </h1>

          <p class="mt-4 max-w-xl text-base leading-relaxed text-indigo-100 md:text-lg">
            Ghost creators know other Ghost creators. That is how a tool this specific finds anyone at all, so half of what they pay is yours.
          </p>

          <div class="mt-8 flex flex-wrap items-center gap-4">
            <a
              :href="JOIN_URL"
              target="_blank"
              rel="noopener"
              class="lift inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3.5 text-base font-bold text-indigo-700 shadow-lg"
            >
              Become an affiliate
              <svg class="icon-nudge h-5 w-5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5-5 5M6 12h12" />
              </svg>
            </a>
            <span class="text-sm text-indigo-100">Takes about two minutes.</span>
          </div>
        </div>

        <div class="relative mt-10 grid gap-4 sm:grid-cols-3">
          <div v-for="stat in HEADLINE_STATS" :key="stat.label" class="rounded-2xl bg-white/10 px-5 py-4 backdrop-blur">
            <p class="text-3xl font-bold md:text-4xl">
              {{ stat.value }}<span class="text-xl md:text-2xl">{{ stat.unit }}</span>
            </p>
            <p class="mt-1 text-sm text-indigo-100">{{ stat.label }}</p>
          </div>
        </div>
      </section>

      <!-- How it works -->
      <div class="pt-4">
        <h2 class="text-center text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Three steps, then it runs by itself
        </h2>
        <p class="mx-auto mt-1.5 max-w-lg text-center text-sm text-slate-500 dark:text-slate-400">
          No dashboard to babysit, no invoices to chase.
        </p>
      </div>

      <div class="grid gap-5 md:grid-cols-3">
        <div
          v-for="step in STEPS"
          :key="step.title"
          class="lift rounded-2xl border border-slate-200 bg-white p-7 dark:border-slate-800 dark:bg-slate-900"
        >
          <div class="flex h-12 w-12 items-center justify-center rounded-xl" :class="TONES[step.tone]">
            <svg class="icon-nudge h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" :d="step.path" />
            </svg>
          </div>
          <p class="mt-5 text-xs font-semibold uppercase tracking-widest" :class="STEP_LABEL[step.tone]">{{ step.step }}</p>
          <p class="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">{{ step.title }}</p>
          <p class="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">{{ step.body }}</p>
        </div>
      </div>

      <!-- What it adds up to -->
      <section class="overflow-hidden rounded-3xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="grid md:grid-cols-2">
          <div class="p-8 md:p-10">
            <p class="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">What it adds up to</p>
            <h3 class="mt-3 text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Ten people is a monthly bill you stop paying.
            </h3>
            <p class="mt-3 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              Recommend PayGlue to ten creators who stay, and the commission covers your own subscription several times over. Nobody has to buy anything they were not already looking for.
            </p>
            <a
              :href="JOIN_URL"
              target="_blank"
              rel="noopener"
              class="lift mt-7 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-bold text-white"
            >
              Start sharing
              <svg class="icon-nudge h-4 w-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5-5 5M6 12h12" />
              </svg>
            </a>
          </div>

          <div class="bg-slate-50 p-8 dark:bg-slate-950/40 md:p-10">
            <div class="w-full">
              <p class="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                Which plan are they on?
              </p>
              <!-- Two by two, not three across: adding Founding as a fourth
                   option left Agency alone on its own row with a gap beside it. -->
              <div class="mt-2 grid grid-cols-2 gap-2">
                <button
                  v-for="plan in plans"
                  :key="plan.key"
                  type="button"
                  class="rounded-lg border px-3 py-2 text-sm font-semibold transition-colors"
                  :class="plan.key === selectedPlanKey
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'"
                  @click="selectedPlanKey = plan.key"
                >
                  {{ plan.name }}
                  <span class="mt-0.5 block text-[11px] font-normal opacity-70">{{ plan.monthly }} €/mo</span>
                </button>
              </div>

              <div class="mt-6 flex items-baseline justify-between">
                <label for="referral-count" class="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                  How many stay
                </label>
                <span class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {{ referrals }} {{ referrals === 1 ? 'referral' : 'referrals' }}
                </span>
              </div>
              <input
                id="referral-count"
                v-model.number="referrals"
                type="range"
                min="1"
                max="25"
                step="1"
                class="mt-2 w-full accent-indigo-600"
              />
              <div class="flex justify-between text-[11px] text-slate-400 dark:text-slate-500">
                <span>1</span><span>25</span>
              </div>

              <div class="mt-6 rounded-2xl border-2 border-indigo-500 bg-indigo-50 px-5 py-4 dark:bg-indigo-500/10">
                <p class="text-3xl font-bold text-indigo-700 dark:text-indigo-300">
                  {{ money(perYear) }}<span class="text-base font-medium"> / year</span>
                </p>
                <p class="mt-1 text-sm text-indigo-900/70 dark:text-indigo-200/70">
                  {{ money(perMonth) }} every month, for as long as they stay
                </p>
              </div>

              <p class="mt-3 text-center text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
                40% of the {{ selectedPlan.monthly }} € monthly price, times {{ referrals }}. If they pay yearly the
                total is a little lower, because the annual plan itself is cheaper.
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- The caveat: present, but not the first thing anybody reads. -->
      <div class="flex items-start gap-3 rounded-xl border border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
        <svg class="mt-0.5 h-5 w-5 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path stroke-linecap="round" d="M12 8h.01M11 12h1v4h1" />
        </svg>
        <p class="text-sm leading-relaxed text-slate-500 dark:text-slate-400">
          <span class="font-medium text-slate-700 dark:text-slate-200">One thing first:</span>
          the programme runs on Creem, our payment provider, so joining means creating a Creem account. It is separate from your PayGlue login. Better you hear it here than after the click.
        </p>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
@keyframes floatUp {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
.rise { animation: floatUp 0.6s cubic-bezier(0.2, 0.7, 0.3, 1) both; }

/* Slow enough to feel alive, not fast enough to compete with the text. */
@keyframes drift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
.living-gradient {
  background: linear-gradient(120deg, #4f46e5, #7c3aed, #4338ca, #6d28d9);
  background-size: 300% 300%;
  animation: drift 14s ease-in-out infinite;
}

@keyframes pulseRing {
  0% { transform: scale(0.85); opacity: 0.55; }
  70%, 100% { transform: scale(1.5); opacity: 0; }
}
.ring::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 9999px;
  border: 2px solid rgba(255, 255, 255, 0.55);
  animation: pulseRing 2.6s ease-out infinite;
}

.lift { transition: transform 0.25s cubic-bezier(0.2, 0.7, 0.3, 1), box-shadow 0.25s; }
.lift:hover { transform: translateY(-5px); box-shadow: 0 18px 40px -18px rgba(79, 70, 229, 0.45); }

.icon-nudge { transition: transform 0.35s cubic-bezier(0.2, 0.7, 0.3, 1); }
.lift:hover .icon-nudge { transform: translateX(3px); }

/* Not a nicety: motion is genuinely unpleasant for some people. */
@media (prefers-reduced-motion: reduce) {
  .rise,
  .living-gradient,
  .ring::after { animation: none !important; }
  .lift,
  .icon-nudge { transition: none !important; }
  .lift:hover { transform: none; }
}
</style>
