import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

for (const size of [
  { width: 1180, height: 740 },
  { width: 880, height: 560 },
]) {
  test.describe(`AURIX viewport ${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test('models panel scrolls, uses accessible inputs and fits the window', async ({ page }) => {
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/');
      await page.getByRole('button', { name: 'Models', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Models & local inference' })).toBeVisible();
      const input = page.getByLabel('Other Ollama model tag');
      await input.scrollIntoViewIfNeeded();
      await expect(input).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      const audit = await new AxeBuilder({ page }).include('.models-panel')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      expect(audit.violations).toEqual([]);
      await page.screenshot({ path: `test-results/models-${size.width}.png`, fullPage: true });
    });

    test('all navigation panels render without runtime exceptions', async ({ page }) => {
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
  });
}
