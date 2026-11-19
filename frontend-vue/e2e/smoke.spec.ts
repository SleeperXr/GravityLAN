import { expect, test, type Page } from '@playwright/test';

// Synthetic; the demo database is thrown away on every run
const PASSWORD = 'e2e-smoke-password';

/** Uncaught errors in the page. Failed requests are left out: the demo backend answers scans with 403 on purpose. */
function pageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

// The second test signs in to the instance the first one set up
test.describe.configure({ mode: 'serial' });

test('a fresh install goes through the setup wizard to the dashboard', async ({ page }) => {
  const errors = pageErrors(page);
  await page.goto('./');

  await page.getByRole('button', { name: 'Next' }).click();

  // Networks: untick every network the host reports, then the wizard offers to skip the scan.
  // The list loads after "Next" and comes in all ticked: reading the checkboxes while it still
  // loads found none, nothing was unticked, and "Skip scan" never appeared (flaky in CI)
  // Loaded once the step's main button is enabled: "Start Scan" is disabled while it loads,
  // "Skip scan" only appears afterwards (no networks found)
  await expect(page.getByRole('button', { name: /^(Start Scan|Skip scan)$/ })).toBeEnabled({ timeout: 30_000 });
  const networks = page.getByRole('checkbox');
  for (const box of await networks.all()) {
    if (await box.isChecked()) await box.uncheck();
  }
  await page.getByRole('button', { name: 'Skip scan' }).click();

  await expect(page.getByRole('heading', { name: 'Configure security' })).toBeVisible();
  await page.getByLabel('Administrator password').fill(PASSWORD);
  await page.getByLabel('Confirm password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Finish' }).click();

  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('signing out, a wrong password and signing in again', async ({ page }) => {
  const errors = pageErrors(page);
  await page.goto('./');
  await page.getByLabel('Admin password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();

  await expect(page.getByRole('heading', { name: 'Authentication required' })).toBeVisible();
  await page.getByLabel('Admin password').fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByText('Invalid password')).toBeVisible();

  await page.getByLabel('Admin password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  expect(errors).toEqual([]);
});
