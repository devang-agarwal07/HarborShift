import { test, expect } from '@playwright/test';

test('apply disruption, inspect recovery, and reset the baseline', async ({ page }, testInfo) => {
  const errors = [];
  const publicRequests = [];
  await page.route(/^https?:\/\/(?!127\.0\.0\.1:5173\/)/, async (route) => {
    publicRequests.push(route.request().url());
    await route.abort();
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Disruption simulator' })).toBeVisible();
  const risk = page.locator('.metrics > div').filter({ hasText: 'Contracts at risk' }).locator('dd');
  await expect(risk).toHaveText('0');
  await page.getByRole('button', { name: 'Apply event' }).click();
  await expect(risk).toHaveText('1');
  await expect(page.getByText('Recommended · DEMO-LOCAL')).toBeVisible();
  await expect(page.locator('.edge.affected').first()).toBeVisible();
  await expect(page.getByText('No option meets the deadline.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'wait', exact: true }).click();
  await expect(page.getByText('Selected recovery')).toBeVisible();
  await expect(page.locator('.edge.chosen')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  expect(publicRequests).toEqual([]);
  if (process.env.HARBORSHIFT_CAPTURE) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `../docs/screenshots/${testInfo.project.name}.png`, fullPage: true });
  }
  await page.getByRole('button', { name: 'Reset', exact: true }).click();
  await expect(risk).toHaveText('0');
  await expect(page.locator('.edge.affected')).toHaveCount(0);
  await expect(page.getByText('Apply an event that affects a shipment')).toBeVisible();
});

test('show a no-route result and keep sample news opt-in', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Apply event' })).toBeEnabled();
  await page.getByRole('button', { name: 'Network', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Route lookup' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Origin', exact: true }).selectOption('P11');
  await page.getByRole('combobox', { name: 'Destination', exact: true }).selectOption('P03');
  await page.getByRole('button', { name: 'Find route' }).click();
  await expect(page.getByRole('status')).toContainText('No route.');
  await page.getByRole('button', { name: 'Disruptions', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Fetch public advisories' })).toBeVisible();
});


test('manual event dates and route closures reach the backend', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Disruption' }).selectOption('manual');
  await page.getByLabel('Simulated date').fill('2027-01-01');
  await page.getByRole('combobox', { name: 'Port', exact: true }).selectOption('P03');
  await page.getByLabel('Event start (optional)').fill('2027-01-01');
  await page.getByLabel('Duration · days').fill('4');
  await page.getByRole('button', { name: 'Apply event' }).click();
  await expect(page.getByText('Recommended · DEMO-LOCAL', { exact: true })).toBeVisible();
  await expect(page.locator('.contract-card')).toContainText('2027-01-21');
  await page.getByRole('button', { name: 'Network', exact: true }).click();
  await page.getByText('Required stops and closures', { exact: true }).click();
  await page.getByLabel('Closed port IDs').fill('P05');
  await page.getByRole('button', { name: 'Find route' }).click();
  await expect(page.getByRole('status')).toContainText('R36, R33, R08');
  await expect(page.getByRole('status')).toContainText('32 days');
});

test('dark theme preserves the scenario and survives a reload', async ({ page }) => {
  await page.goto('/');
  const theme = page.getByRole('button', { name: 'Dark theme' });
  const root = page.locator('html');
  await expect(root).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: 'Apply event' }).click();
  await expect(page.getByText('Late delivery', { exact: true })).toBeVisible();
  await theme.click();
  await expect(theme).toHaveAttribute('aria-pressed', 'true');
  await expect(root).toHaveCSS('color-scheme', 'dark');
  await expect(page.getByText('Late delivery', { exact: true })).toBeVisible();
  await expect(page.locator('.edge.affected').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.reload();
  await expect(root).toHaveAttribute('data-theme', 'dark');
  await expect(theme).toHaveAttribute('aria-pressed', 'true');
  await theme.click();
  await expect(root).toHaveCSS('color-scheme', 'light');
});

test('shipping globe rotates, zooms, resets, and selects a port', async ({ page }, info) => {
  await page.goto('/');
  const globe = page.getByRole('region', { name: 'Rotatable shipping globe' });
  const land = globe.locator('.globe-land');
  await expect(land).toBeVisible();
  await globe.scrollIntoViewIfNeeded();
  await expect.poll(() => globe.locator('svg').evaluate((svg) =>
    Math.abs(svg.viewBox.baseVal.width - svg.clientWidth))).toBeLessThan(1);
  const initialLand = await land.getAttribute('d');
  const area = await globe.boundingBox();
  await page.mouse.move(area.x + area.width * .48, area.y + area.height * .15);
  await page.mouse.down();
  await page.mouse.move(area.x + area.width * .65, area.y + area.height * .21, { steps: 8 });
  await page.mouse.up();
  await expect(land).not.toHaveAttribute('d', initialLand);

  const ocean = globe.locator('.globe-ocean');
  const initialOcean = await ocean.getAttribute('d');
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect(ocean).not.toHaveAttribute('d', initialOcean);
  await page.getByRole('button', { name: 'Reset view' }).click();
  await expect(land).toHaveAttribute('d', initialLand);
  await globe.press('ArrowRight');
  await expect(land).not.toHaveAttribute('d', initialLand);
  await page.getByRole('button', { name: 'Show all ports' }).click();
  await page.getByLabel('Go to port').selectOption('P16');
  await expect(page.getByRole('heading', { name: 'Departures from Singapore' })).toBeVisible();
  await expect(globe.getByRole('button', { name: 'Singapore' })).toHaveAttribute('aria-pressed', 'true');

  if (process.env.HARBORSHIFT_GLOBE_CAPTURE) {
    await page.getByRole('button', { name: 'Focus on demo' }).click();
    await page.getByRole('button', { name: 'Reset view' }).click();
    await page.getByRole('button', { name: 'Apply event' }).click();
    await expect(page.getByText('Late delivery', { exact: true })).toBeVisible();
    if (info.project.name === 'mobile') await page.getByRole('button', { name: 'Dark theme' }).click();
    await page.locator('.network').screenshot({ path: `${process.env.HARBORSHIFT_GLOBE_CAPTURE}/HarborShift-globe-${info.project.name}.png` });
  }
});
