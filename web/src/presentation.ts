import type { HazardState, Weather } from './types';

// Colour tokens follow the guide (Section 8.2). `ink` is the text-safe variant,
// `soft` a tint for surfaces; every state also carries a non-colour symbol.
export const STATES: Record<HazardState, { label: string; color: string; ink: string; soft: string; symbol: string; icon: string; summary: string }> = {
  NORMAL: { label: 'Normal', color: '#2e7d32', ink: '#256b2a', soft: '#eef5ee', symbol: '✓', icon: 'check', summary: 'No current simulated water hazard.' },
  WATCH: { label: 'Watch', color: '#f2c94c', ink: '#6b5410', soft: '#fbf5e3', symbol: '!', icon: 'alert', summary: 'Water warrants monitoring near the tram corridor.' },
  WARNING: { label: 'Warning', color: '#ed7d31', ink: '#a4460e', soft: '#fdf1e8', symbol: '!', icon: 'alert', summary: 'Elevated water. Local disruption risk is high.' },
  CRITICAL: { label: 'Critical', color: '#d32f2f', ink: '#b22424', soft: '#fcebeb', symbol: '!', icon: 'alert', summary: 'Severe simulated flood risk near the corridor.' },
  UNKNOWN: { label: 'Unknown', color: '#7a7f85', ink: '#5b6168', soft: '#f0f1f0', symbol: '?', icon: 'question', summary: 'Insufficient trustworthy sensor observations.' },
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
export function humanize(value: string) { return value.charAt(0) + value.slice(1).toLowerCase().replaceAll('_', ' '); }
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

// Rain is context, never evidence: it is shown only for a fresh, connected
// observation whose source is allowed in the current operating mode (mock rain
// in simulation, a physical gauge in normal operation) and within 0–200 mm/h.
export function currentRain(weather: Weather | undefined | null, connected: boolean, mode?: string): number | null {
  if (!connected || !weather || weather.freshness !== 'fresh') return null;
  if (weather.source === 'mock' ? mode !== 'simulation' : weather.source === 'physical' ? mode !== 'normal' : true) return null;
  const value = weather.intensityMmPerHour;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 200 ? value : null;
}
// Every marker is labelled by its own record source, even inside a mixed response.
export function vehicleTitle(vehicle: { vehicleId?: string; source?: string; observedAt?: string }, transportSource?: string) {
  const source = vehicle.source ?? (transportSource && transportSource !== 'mixed' ? transportSource : undefined);
  const id = vehicle.vehicleId ?? '';
  const name = source === 'mock' ? `Mock demo tram ${id}` : source === 'transport-victoria' ? `Observed tram ${id}` : source === 'fixture' ? `Fixture tram ${id}` : `Tram ${id} · Unconfirmed source`;
  return `${name.trim()}${vehicle.observedAt ? ` · ${vehicle.observedAt}` : ''}`;
}
export function transportSourceLabel(source?: string) {
  switch (source) {
    case 'mixed': return 'Live + mock tram data';
    case 'mock': return 'Mock tram data';
    case 'fixture': return 'Synthetic transport fixture';
    default: return 'Transport Victoria · observed';
  }
}
