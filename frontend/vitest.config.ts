import { defineConfig } from 'vitest/config'

/**
 * A separate config for the unit tests.
 *
 * `vite.config.ts` builds the SPA into `backend/app/static/app` — reusing it
 * would make vitest write its artefacts into the backend tree. The test run
 * therefore uses this file only.
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['src/setupTests.ts'],
    restoreMocks: true,
  },
})
