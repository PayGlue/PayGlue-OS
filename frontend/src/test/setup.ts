// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import '@testing-library/jest-dom'

// Node 25 ships its own global `localStorage`, and it wins over the one jsdom
// would have installed -- on window as well as on globalThis, so there is no
// working implementation left to point at. Without --localstorage-file it is
// inert: `typeof localStorage !== 'undefined'` passes, then getItem is not a
// function, and every module that touches storage at import time dies. CI runs
// an older Node and never sees it; on Node 25 the whole suite fails to load.
// Substitute a real in-memory Storage when the ambient one cannot be used.
if (typeof localStorage === 'undefined' || typeof localStorage.getItem !== 'function') {
  const store = new Map<string, string>()
  const stub: Storage = {
    get length() {
      return store.size
    },
    key: (i) => [...store.keys()][i] ?? null,
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => void store.set(k, String(v)),
    removeItem: (k) => void store.delete(k),
    clear: () => store.clear(),
  }
  for (const target of [globalThis, window]) {
    Object.defineProperty(target, 'localStorage', { value: stub, configurable: true, writable: true })
  }
}
