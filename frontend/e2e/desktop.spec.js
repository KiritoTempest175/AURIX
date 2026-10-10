import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('model setup is labeled, scrollable, and does not overflow horizontally', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Models', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Local models', exact: true })).toBeVisible();
  await expect(page.getByLabel('Full path to the GGUF file')).toBeVisible();
  const checksum = page.getByLabel('Publisher SHA-256 checksum');
  await checksum.scrollIntoViewIfNeeded();
  await expect(checksum).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  // Audit the new panel; broader application WCAG review remains separate.
  const audit = await new AxeBuilder({ page }).include('.models-panel')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
  await page.screenshot({ path: `test-results/models-${page.viewportSize().width}.png`, fullPage: true });
});

test('every navigation item opens its panel without renderer exceptions', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  for (const name of ['Models', 'Email', 'Telemetry', 'Memory', 'System', 'Activity', 'Command']) {
    const button = page.getByRole('button', { name, exact: true });
    await button.click();
    await expect(button).toHaveAttribute('aria-current', 'page');
  }
  expect(errors).toEqual([]);
});
