// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useCollapsedList } from '../collapsedList'

const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `r${i + 1}` }))

describe('useCollapsedList', () => {
  it('shows every row when there are three or fewer', () => {
    const { visible, hiddenCount, canCollapse } = useCollapsedList(ref(rows(3)))
    expect(visible.value.map(r => r.id)).toEqual(['r1', 'r2', 'r3'])
    expect(hiddenCount.value).toBe(0)
    expect(canCollapse.value).toBe(false)
  })

  it('shows the first three and counts the rest', () => {
    const { visible, hiddenCount } = useCollapsedList(ref(rows(7)))
    expect(visible.value.map(r => r.id)).toEqual(['r1', 'r2', 'r3'])
    expect(hiddenCount.value).toBe(4)
  })

  it('expands and collapses again', () => {
    const list = useCollapsedList(ref(rows(5)))
    list.toggle()
    expect(list.visible.value).toHaveLength(5)
    expect(list.hiddenCount.value).toBe(0)
    expect(list.canCollapse.value).toBe(true)
    list.toggle()
    expect(list.visible.value).toHaveLength(3)
  })

  it('keeps the row being edited in view', () => {
    const active = ref<string | null>('r6')
    const { visible, hiddenCount } = useCollapsedList(ref(rows(6)), active)
    expect(visible.value.map(r => r.id)).toEqual(['r1', 'r2', 'r3', 'r6'])
    expect(hiddenCount.value).toBe(2)
  })
})
