// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { ref } from 'vue'

const STORAGE_KEY = 'payglue_header_script_installed'
const _isInstalled = ref(
  typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'true',
)

export function useHeaderScriptStatus() {
  function markInstalled() {
    localStorage.setItem(STORAGE_KEY, 'true')
    _isInstalled.value = true
  }
  function markNotInstalled() {
    localStorage.removeItem(STORAGE_KEY)
    _isInstalled.value = false
  }
  return { isInstalled: _isInstalled, markInstalled, markNotInstalled }
}
