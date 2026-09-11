// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// Type side of the jest-dom matchers for vitest 5. See setup.ts for why this
// is not `import '@testing-library/jest-dom/vitest'`: vitest 5's `Assertion`
// takes two type parameters, R (what a matcher returns) and T (the value under
// test), and jest-dom's bundled augmentation still declares one.
import 'vitest'
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers'

declare module 'vitest' {
  interface Assertion<R, T> extends TestingLibraryMatchers<T, R> {}
  interface AsymmetricMatchersContaining extends TestingLibraryMatchers<any, any> {}
}
