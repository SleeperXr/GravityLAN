import { defineConfig, devices } from '@playwright/test';

/**
 * Browser smoke tests against the demo backend (scripts/dev_demo.py --fresh): a new install, no scans, no SSH,
 * listening on 127.0.0.1 only. Both servers are started here and never reused, so a test cannot attach to a
 * real GravityLAN that happens to run on port 8000 or 5174.
 */
const python = process.env.GRAVITYLAN_E2E_PYTHON ?? 'python';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5174/frontend-vue/',
    locale: 'en-US',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" ../scripts/dev_demo.py --fresh`,
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --strictPort',
      url: 'http://127.0.0.1:5174/frontend-vue/',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
