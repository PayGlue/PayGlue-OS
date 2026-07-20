// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

export type PaletteItem = { label: string; sectionLabel: string; to: string }

const props = defineProps<{
  open: boolean
  items: PaletteItem[]
}>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const router = useRouter()
const query = ref('')
const activeIndex = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.items
  return props.items.filter(
    (i) => i.label.toLowerCase().includes(q) || i.sectionLabel.toLowerCase().includes(q),
  )
})

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    query.value = ''
    activeIndex.value = 0
    await nextTick()
    inputEl.value?.focus()
  },
)
watch(filtered, () => { activeIndex.value = 0 })

const close = () => emit('update:open', false)

const select = (item: PaletteItem) => {
  router.push(item.to)
  close()
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, filtered.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = filtered.value[activeIndex.value]
    if (item) select(item)
  } else if (e.key === 'Escape') {
    close()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[60] flex items-start justify-center bg-slate-900/70 px-4 pt-[14vh] backdrop-blur-sm"
      @click.self="close"
    >
      <div class="w-full max-w-lg overflow-hidden rounded-2xl border border-slate-700 bg-slate-800 shadow-2xl">
        <div class="flex items-center gap-3 border-b border-slate-700 px-4 py-3">
          <svg class="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M21 21l-4.3-4.3" />
          </svg>
          <input
            ref="inputEl"
            v-model="query"
            type="text"
            placeholder="Search Polar, Billing, Team…"
            class="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none"
            @keydown="onKeydown"
          />
          <kbd class="rounded border border-slate-600 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">Esc</kbd>
        </div>
        <div class="max-h-80 overflow-y-auto p-1.5">
          <p v-if="!filtered.length" class="px-3 py-8 text-center text-sm text-slate-500">No matches.</p>
          <button
            v-for="(item, i) in filtered"
            :key="item.to"
            type="button"
            class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors"
            :class="i === activeIndex ? 'bg-indigo-600 text-white' : 'text-slate-200 hover:bg-slate-700'"
            @mouseenter="activeIndex = i"
            @click="select(item)"
          >
            <span class="font-medium">{{ item.label }}</span>
            <span class="text-xs" :class="i === activeIndex ? 'text-indigo-200' : 'text-slate-500'">{{ item.sectionLabel }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
