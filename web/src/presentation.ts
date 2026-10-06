import type { HazardState } from './types';

export const STATES: Record<HazardState, { label: string; color: string; ink: string; symbol: string; summary: string }> = {
  NORMAL: { label: 'Normal', color: '#2e7d32', ink: '#286d2c', symbol: '✓', summary: 'No current simulated water hazard.' },
  WATCH: { label: 'Watch', color: '#f2c94c', ink: '#705710', symbol: '!', summary: 'Water warrants monitoring near the tram corridor.' },
  WARNING: { label: 'Warning', color: '#ed7d31', ink: '#a8460c', symbol: '!', summary: 'Elevated water. Local disruption risk is high.' },
  CRITICAL: { label: 'Critical', color: '#d32f2f', ink: '#bb2424', symbol: '!', summary: 'Severe simulated flood risk near the corridor.' },
  UNKNOWN: { label: 'Unknown', color: '#7a7f85', ink: '#596168', symbol: '?', summary: 'Insufficient trustworthy sensor observations.' },
};
export function stateStyle(state: HazardState) { return STATES[state] ?? STATES.UNKNOWN; }
export function formatTime(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not available';
  return new Intl.DateTimeFormat('en-AU', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Australia/Melbourne' }).format(new Date(value));
}
export function formatAge(value: string | null | undefined, now: number) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'No observation';
  const sec = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  return sec < 60 ? `${sec}s ago` : sec < 3600 ? `${Math.floor(sec / 60)}m ago` : `${Math.floor(sec / 3600)}h ago`;
}
export function delayLabel(seconds: number | undefined) {
  if (seconds === undefined || !Number.isFinite(seconds)) return 'No delay estimate';
  if (seconds === 0) return 'On schedule';
  return `${Math.round(Math.abs(seconds) / 60)} min ${seconds > 0 ? 'late' : 'early'}`;
}
export const SCENARIOS = [
  ['normal-steady', 'Normal conditions', 'Steady, low water'],
  ['water-rising', 'Water rising', 'A gradual rise through all risk states'],
  ['critical-rise', 'Rapid rise', 'A faster rise to critical'],
  ['recovery', 'Water receding', 'A controlled return to normal'],
  ['sensor-stale', 'Stale sensor', 'An observation that is out of date'],
  ['sensor-fault', 'Sensor fault', 'An untrustworthy measurement'],
  ['transport-feed-unavailable', 'Transport outage', 'A failed realtime transport feed'],
  ['official-alert-present', 'Service alert fixture', 'Synthetic service disruption for testing'],
] as const;
