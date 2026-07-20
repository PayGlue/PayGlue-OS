// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// App-wide light / dark / system theme. A `.dark` class on <html> drives the
// Tailwind `dark:` variants. "system" follows the OS preference (which itself
// usually follows time of day) and updates live when the OS flips.
import { ref } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'payglue:theme'

const prefersDark = () =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-color-scheme: dark)').matches

const readStored = (): ThemeMode => {
  if (typeof localStorage === 'undefined') return 'system'
  const value = localStorage.getItem(STORAGE_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

// Module-level singletons so every component shares one source of truth.
const mode = ref<ThemeMode>(readStored())
const systemDark = ref(prefersDark())

const resolvedDark = () => mode.value === 'dark' || (mode.value === 'system' && systemDark.value)

const apply = () => {
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', resolvedDark())
  }
}

// Keep "system" mode in sync with the OS while the app is open.
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
    systemDark.value = event.matches
    apply()
  })
}
apply()

const ORDER: ThemeMode[] = ['light', 'dark', 'system']

export function useTheme() {
  const setMode = (next: ThemeMode) => {
    mode.value = next
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, next)
    apply()
  }
  const cycle = () => setMode(ORDER[(ORDER.indexOf(mode.value) + 1) % ORDER.length])
  return { mode, setMode, cycle, isDark: resolvedDark }
}
