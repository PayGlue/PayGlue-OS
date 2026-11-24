// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// Saved lists above an editor (buttons, paywalls, pricing tables) show the
// first few rows, so the editor below never slides far down the page.
import { computed, ref, type Ref } from 'vue'

export const COLLAPSED_ROWS = 3

export function useCollapsedList<T extends { id: string }>(
  items: Ref<T[]>,
  activeId?: Ref<string | null>,
  limit = COLLAPSED_ROWS,
) {
  const expanded = ref(false)

  const visible = computed(() => {
    const all = items.value
    if (expanded.value || all.length <= limit) return all
    const head = all.slice(0, limit)
    // The row being edited stays in view even when it sits below the fold.
    const active = activeId?.value
    if (active && !head.some(i => i.id === active)) {
      const row = all.find(i => i.id === active)
      if (row) return [...head, row]
    }
    return head
  })

  const hiddenCount = computed(() => Math.max(0, items.value.length - visible.value.length))
  const canCollapse = computed(() => expanded.value && items.value.length > limit)

  function toggle() {
    expanded.value = !expanded.value
  }

  return { visible, hiddenCount, canCollapse, expanded, toggle }
}
