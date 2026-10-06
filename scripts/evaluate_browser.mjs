// Run with node scripts/evaluate_browser.mjs while python run.py is running.
// Uses the application's real HTTP/SSE/React path, not mocked browser data.
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'web/package.json'));
const { chromium, expect } = require('@playwright/test');
const targets = JSON.parse(await readFile(path.join(root, 'config/evaluation.json'), 'utf8'));
const startedAt = new Date().toISOString();
const directory = path.join(root, 'artifacts', `browser-evaluation-${startedAt.replaceAll(':', '-').replaceAll('.', '-')}`);
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const browserRenders = new Map();
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
page.on('response', response => {
  if (response.url().endsWith('/api/v1/telemetry/render') && response.ok()) {
    const sample = response.request().postDataJSON();
    browserRenders.set(sample.readingId, sample);
  }
});
const base = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000';
const report = { startedAt, targets, renderer: null, transitionChecks: [], browserErrors: errors, failures: [], reviewerAssessment: 'NOT RUN: requires independent human reviewers' };
const command = async (endpoint, data = {}) => {
  const response = await page.request.post(`${base}/api/v1${endpoint}`, { data });
  if (!response.ok()) throw new Error(`${endpoint}: HTTP ${response.status()}`);
  return response.json();
};
const exportRun = async () => (await page.request.get(`${base}/api/v1/events/export`)).json();
const p95 = values => [...values].sort((a, b) => a - b)[Math.ceil(values.length * .95) - 1] ?? null;
const screenshot = name => page.screenshot({ path: path.join(directory, name), animations: 'disabled' });
try {
  await command('/settings', { mode: 'simulation', impactScope: 'local_segment' });
  await command('/scenarios/reset');
  await page.goto(base);
  await expect(page.getByRole('button', { name: 'Run scenario' })).toBeEnabled();
  report.renderer = await page.getByTestId('map').getAttribute('data-renderer');
  // Measure actual 1Hz observations. The bounded SSE queue intentionally coalesces
  // superseded values; rapid POSTs are not guaranteed one browser frame each.
  // Capture THIS browser's reports, because other open browsers can report first.
  await expect.poll(() => browserRenders.size, { timeout: 45000, intervals: [500] }).toBeGreaterThanOrEqual(24);
  for (const [level, state] of [[12, 'Normal'], [35, 'Watch'], [60, 'Warning'], [90, 'Critical']]) {
    await command('/scenarios/manual', { level });
    await expect(page.getByTestId('hazard-state')).toHaveText(state, { timeout: 25000 });
    report.transitionChecks.push({ level, expected: state, actual: await page.getByTestId('hazard-state').innerText(), at: new Date().toISOString() });
    await screenshot(`${state.toLowerCase()}.png`);
  }
  report.animation = await page.evaluate(() => new Promise(resolve => {
    let start = null; const intervals = []; let previous;
    function frame(now) {
      if (start === null) start = now;
      if (previous !== undefined) intervals.push(now - previous);
      previous = now;
      if (now - start < 3000) requestAnimationFrame(frame);
      else resolve({ frames: intervals.length, elapsedMs: now - start, framesPerSecond: intervals.length / ((now - start) / 1000), maxFrameIntervalMs: Math.max(...intervals), measurement: 'Headless browser requestAnimationFrame cadence; not device GPU benchmarking' });
    }
    requestAnimationFrame(frame);
  }));
  await command('/settings', { impactScope: 'full_route_demo' });
  await expect(page.getByLabel('Highlight impact')).toHaveValue('full_route_demo');
  await page.getByRole('button', { name: 'View full route', exact: true }).click();
  await screenshot('critical-full-route-impact.png');
  await page.getByRole('button', { name: 'Return to Stop 116', exact: true }).click();
  await command('/scenarios/manual', { level: 10 });
  await expect(page.getByTestId('hazard-state')).toHaveText('Normal', { timeout: 25000 });
  report.transitionChecks.push({ level: 10, expected: 'Normal after controlled recovery', actual: await page.getByTestId('hazard-state').innerText() });
  const run = await exportRun();
  await writeFile(path.join(directory, 'events.json'), JSON.stringify(run, null, 2));
  const observations = new Map(run.events.filter(event => event.type === 'reading-evaluated').map(event => [event.readingId, event]));
  const samples = [...browserRenders.values()].filter(sample => observations.has(sample.readingId)).map(sample => ({
    ...observations.get(sample.readingId), ...sample,
    latencyMs: Date.parse(sample.renderedAt) - Date.parse(observations.get(sample.readingId).observedAt),
    serverLatencyMs: Date.parse(sample.renderedAt) - Date.parse(observations.get(sample.readingId).receivedAt),
  }));
  await writeFile(path.join(directory, 'browser-render-samples.json'), JSON.stringify(samples, null, 2));
  Object.assign(report, { runId: run.runId, buildId: run.buildId, configurationHash: run.configurationHash, gtfsDatasetVersion: run.gtfsDatasetVersion,
    latencySampleCount: samples.length, observedToRenderP95Ms: p95(samples.map(sample => sample.latencyMs)),
    serverToRenderP95Ms: p95(samples.map(sample => sample.serverLatencyMs)),
    telemetryNote: 'Browser wall-clock timestamp after two animation frames approximates paint. Localhost only; not a synchronized device measurement.' });
  await command('/scenarios/sensor-stale/start');
  await expect(page.getByTestId('hazard-state')).toHaveText('Unknown');
  await screenshot('unknown.png');
  await command('/scenarios/official-alert-present/start');
  await expect(page.getByText('SYNTHETIC ALERT · TEST ONLY').first()).toBeVisible();
  await screenshot('synthetic-alert.png');
  await command('/scenarios/manual', { level: 60 });
  await expect(page.getByTestId('hazard-state')).toHaveText('Warning', { timeout: 25000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot('mobile-collapsed.png');
  await page.getByRole('button', { name: 'View details & controls' }).click();
  await screenshot('mobile-expanded.png');
  report.checks = {
    minimumSamples: report.latencySampleCount >= targets.minimumLatencySamples,
    observedLatency: report.observedToRenderP95Ms <= targets.maxP95ObservedToRenderMs,
    serverLatency: report.serverToRenderP95Ms <= targets.maxP95ServerToRenderMs,
    browserErrors: errors.length <= targets.maximumBrowserErrors,
    animationCadence: report.animation.framesPerSecond >= targets.minimumAnimationFramesPerSecond,
  };
} catch (error) {
  report.failures.push(error.message);
  const failedRun = await exportRun().catch(() => null);
  if (failedRun) await writeFile(path.join(directory, 'events-at-failure.json'), JSON.stringify(failedRun, null, 2));
  await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => undefined);
} finally {
  await command('/settings', { mode: 'simulation', impactScope: 'local_segment' }).catch(() => undefined);
  await command('/scenarios/reset').catch(() => undefined);
  await writeFile(path.join(directory, 'results.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ directory, ...report }, null, 2));
if (report.failures.length || Object.values(report.checks ?? {}).some(pass => !pass)) process.exitCode = 1;
