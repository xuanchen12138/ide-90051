import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';

async function command(request: APIRequestContext, path: string, data: unknown = {}) {
  const response = await request.post(`/api/v1${path}`, { data });
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
}
async function level(request: APIRequestContext, page: Page, value: number, state: string, timeout = 15000) {
  await command(request, '/scenarios/manual', { level: value });
  await expect(page.getByTestId('hazard-state')).toHaveText(state, { timeout });
  await expect(page.getByTestId('scenario-level')).toHaveText(String(value));
}

// One worker prevents shared scenario interference. Each test resets the runtime,
// so a failure must not suppress the independent acceptance cases that follow.
test.beforeEach(async ({ request, page }) => {
  await command(request, '/settings', { mode: 'simulation', impactScope: 'local_segment' });
  await command(request, '/scenarios/reset');
  await page.goto('/');
  await expect(page.getByTestId('map')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeEnabled();
});

test('verified map and manual normal → watch → warning → critical → recovery', async ({ page, request }) => {
  const site = await (await request.get('/api/v1/site')).json();
  expect(site.gtfsStopIds.length).toBeGreaterThan(0);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Southbank, Melbourne');
  await expect(page.getByText('Simulated impact — not an official service status.', { exact: true })).toBeVisible();
  await level(request, page, 10, 'Normal');
  await level(request, page, 35, 'Watch');
  await level(request, page, 60, 'Warning');
  await page.getByLabel('Highlight impact').selectOption('full_route_demo');
  await level(request, page, 90, 'Critical');
  await expect(page.getByText('Simulated impact — not an official service status.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Highlight impact')).toHaveValue('full_route_demo');
  if (await page.getByTestId('map').getAttribute('data-renderer') === 'offline') {
    const allDisplayedRoutes = page.locator('.route-stroke');
    expect(await allDisplayedRoutes.count()).toBeGreaterThan(0);
    expect(await page.locator('.route-stroke[stroke-width="4"]').count()).toBeGreaterThan(0);
    for (const route of await allDisplayedRoutes.all()) {
      await expect(route).toHaveAttribute('data-risk', 'CRITICAL');
      await expect(route).toHaveAttribute('stroke', '#d32f2f');
    }
    await expect(page.getByTestId('flood-overlay')).toBeVisible();
  }
  // Three recovery steps each retain their configured five-second dwell. Allow
  // those 15 seconds plus the one-second sensor scheduler and browser margin.
  await level(request, page, 10, 'Normal', 25000);
});

test('cached Melbourne basemap has real geographic layers and working camera controls', async ({ page, request }) => {
  const response = await request.get('/api/v1/site/basemap');
  expect(response.ok()).toBeTruthy();
  const geography = await response.json();
  expect(geography.type).toBe('FeatureCollection');
  expect(geography.features.length).toBeGreaterThan(0);

  const map = page.getByTestId('map');
  await expect(map).toHaveAttribute('data-basemap', 'osm');
  for (const kind of ['building', 'road', 'bridge', 'water']) {
    const features = map.locator(`path[data-map-kind="${kind}"]`);
    await expect(features.first()).toBeAttached();
    expect(await features.count(), `${kind} source geometries`).toBeGreaterThan(0);
    expect(await features.first().getAttribute('d'), `${kind} rendered geometry`).toMatch(/[ML]/);
  }
  await expect(map.locator('text').filter({ hasText: /Yarra/i }).first()).toBeVisible();
  await expect(map.locator('text').filter({ hasText: /Crown|Melbourne Convention|South Melbourne Market|Eureka/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /OpenStreetMap/i })).toBeVisible();

  const road = map.locator('path[data-map-kind="road"]').first();
  const screenMatrix = () => road.evaluate(element => {
    const matrix = (element as SVGGraphicsElement).getScreenCTM();
    if (!matrix) throw new Error('Rendered road has no screen transform');
    return [matrix.a, matrix.d, matrix.e, matrix.f].map(value => Math.round(value * 10000) / 10000);
  });
  const initial = await screenMatrix();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect.poll(screenMatrix).not.toEqual(initial);
  const zoomed = await screenMatrix();
  const interactiveMap = map.locator('svg[tabindex="0"]');
  await interactiveMap.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(screenMatrix).not.toEqual(zoomed);
  await page.getByRole('button', { name: 'Return to Stop 116', exact: true }).click();
  await expect.poll(screenMatrix).toEqual(initial);
  // Zooming out must simplify paths, not remove rivers/building footprints.
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
  await expect(map.locator('path[data-map-kind="water"]').first()).toBeAttached();
  await expect(map.locator('path[data-map-kind="building"]').first()).toBeAttached();
  await page.route('https://**', route => route.abort());
  await page.reload();
  await expect(map).toHaveAttribute('data-basemap', 'osm');
  await expect(map.locator('text').filter({ hasText: /Yarra/i }).first()).toBeVisible();
});

test('missing street snapshot visibly degrades while GTFS and risk updates still work', async ({ page, request }) => {
  await page.route('**/api/v1/site/basemap', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"local_basemap_unavailable"}' }));
  await page.reload();
  await expect(page.getByText('Street data unavailable · verified GTFS only')).toBeVisible();
  await expect(page.getByTestId('map')).toHaveAttribute('data-basemap', 'unavailable');
  await expect(page.getByTestId('stop-marker')).toHaveCount(2);
  await level(request, page, 60, 'Warning');
  await expect(page.locator('.route-stroke[data-risk="WARNING"]').first()).toBeVisible();
});

test('all controls and reload retain a running backend scenario', async ({ page }) => {
  await page.getByLabel('Choose a scenario').selectOption('water-rising');
  await page.getByRole('button', { name: 'Run scenario' }).click();
  await expect(page.locator('.playback-status')).toContainText('Water rising');
  await page.getByRole('button', { name: 'Pause scenario', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Resume scenario', exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Resume scenario', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Resume scenario', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause scenario', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Reset scenario', exact: true }).click();
  await expect(page.locator('.playback-status')).toContainText('Normal conditions');
});

test('stale and fault sensors become unknown, and fixture alerts are explicitly synthetic', async ({ page }) => {
  for (const scenario of ['sensor-stale', 'sensor-fault']) {
    await page.getByLabel('Choose a scenario').selectOption(scenario);
    await page.getByRole('button', { name: 'Run scenario' }).click();
    await expect(page.getByTestId('hazard-state')).toHaveText('Unknown');
    if (await page.getByTestId('map').getAttribute('data-renderer') === 'offline') {
      await expect(page.locator('[data-risk="UNKNOWN"]').first()).toHaveAttribute('stroke-dasharray', '10 8');
    }
  }
  await page.getByLabel('Choose a scenario').selectOption('official-alert-present');
  await page.getByRole('button', { name: 'Run scenario' }).click();
  await expect(page.getByText('SYNTHETIC ALERT · TEST ONLY').first()).toBeVisible();
  await expect(page.getByTestId('service-state')).not.toHaveText('Normal');
  await expect(page.getByText('Simulated impact — not an official service status.', { exact: true })).toBeVisible();
});

test('normal operation does not recycle mock observations', async ({ page }) => {
  await page.getByRole('button', { name: 'Normal operation', exact: true }).click();
  await expect(page.getByTestId('hazard-state')).toHaveText('Unknown');
  await expect(page.getByText('Normal operation accepts physical sensor observations.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run scenario' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Simulation mode', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeEnabled();
});

test('named transport outage is explicit while the sensor and map keep working', async ({ page }) => {
  await page.getByLabel('Choose a scenario').selectOption('transport-feed-unavailable');
  await page.getByRole('button', { name: 'Run scenario' }).click();
  await expect(page.locator('.playback-status')).toContainText('Transport outage');
  await expect(page.getByText('SYNTHETIC TRANSPORT FIXTURE', { exact: true })).toBeVisible();
  await expect(page.getByTestId('service-state')).toHaveText('Unknown');
  await expect(page.locator('.source-line .health-label')).toHaveText('unavailable');
  await expect(page.getByText('Current service conditions cannot be confirmed.')).toBeVisible();
  await expect(page.getByTestId('map')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeEnabled();
  await page.locator('.data-details summary').click();
  const transportFeeds = page.locator('.feed-row').filter({ has: page.locator('.feed-error') });
  expect(await transportFeeds.count()).toBe(3);
  for (const feed of await transportFeeds.all()) await expect(feed.locator('.health-label')).toHaveText('unavailable');
});

test('failed SSE connection marks retained observations as stale', async ({ page }) => {
  await page.route('**/api/v1/events', route => route.abort());
  await page.reload();
  await expect(page.getByText('Connection lost.', { exact: true })).toBeVisible();
  await expect(page.getByTestId('hazard-state')).toHaveText('Unknown');
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeDisabled();
});

test('mobile bottom sheet, keyboard access, and reduced motion', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await level(request, page, 60, 'Warning');
  await expect(page.getByTestId('hazard-state')).toBeVisible();
  await expect(page.locator('.always-visible-sources')).toContainText('Simulated sensor');
  await expect(page.locator('.always-visible-sources')).toContainText('Updated');
  await expect(page.getByRole('button', { name: 'Run scenario' })).not.toBeVisible();
  await page.getByRole('button', { name: 'View details & controls' }).click();
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeVisible();
  await page.getByRole('button', { name: 'Hide details' }).click();
  if (await page.getByTestId('map').getAttribute('data-renderer') === 'offline') {
    const map = page.getByRole('img', { name: 'Verified Route 58 geometry', exact: false });
    await map.focus();
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('+');
    await expect(map).toBeFocused();
    const animation = await page.locator('.water-contour').evaluate(el => getComputedStyle(el).animationName);
    expect(animation).toBe('none');
  }
});
