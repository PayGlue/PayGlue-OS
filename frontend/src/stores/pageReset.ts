// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Clicking the page you are already on should bring you back to its start.
 *
 * The router ignores a navigation to the current route, so a view with an
 * open editor stayed exactly where it was when the breadcrumb or the nav
 * item was clicked. The shell bumps this counter on such a click; views with
 * an editor watch it and close the editor.
 */
export const usePageResetStore = defineStore('pageReset', () => {
  const tick = ref(0)
  function reset() {
    tick.value++
  }
  return { tick, reset }
})
