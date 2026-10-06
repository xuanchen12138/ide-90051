import { describe, expect, it } from 'vitest';
import { delayLabel, formatAge, formatTime, SCENARIOS, stateStyle } from './presentation';
import { featureLines } from './MapView';
import type { Feature } from './types';

describe('provenance and status presentation', () => {
  it('retains non-colour meaning for every backend state', () => {
    for (const state of ['NORMAL', 'WATCH', 'WARNING', 'CRITICAL', 'UNKNOWN'] as const) {
      const style = stateStyle(state);
      expect(style.label).toBeTruthy();
      expect(style.symbol).toBeTruthy();
      expect(style.summary).toBeTruthy();
    }
    expect(stateStyle('UNKNOWN').summary).toContain('Insufficient');
    expect(stateStyle('CRITICAL').summary).toContain('simulated');
  });
  it('never manufactures timestamps for absent or malformed observations', () => {
    expect(formatTime(null)).toBe('Not available');
    expect(formatTime('invalid')).toBe('Not available');
    expect(formatAge(undefined, Date.now())).toBe('No observation');
    expect(formatTime('2026-09-22T00:00:00Z')).toBe('10:00:00');
  });
  it('handles early, late, zero, and unknown delay estimates', () => {
    expect(delayLabel(-120)).toBe('2 min early');
    expect(delayLabel(120)).toBe('2 min late');
    expect(delayLabel(0)).toBe('On schedule');
    expect(delayLabel(undefined)).toBe('No delay estimate');
  });
  it('offers the eight exact reproducible backend scenarios', () => {
    expect(SCENARIOS.map(s => s[0])).toEqual(['normal-steady', 'water-rising', 'critical-rise', 'recovery', 'sensor-stale', 'sensor-fault', 'transport-feed-unavailable', 'official-alert-present']);
  });
});

describe('verified geometry rendering', () => {
  it('preserves GTFS coordinates without synthesizing map geometry', () => {
    const coordinates = [[144.958, -37.826], [144.959, -37.827]] as [number, number][];
    const feature: Feature = { type: 'Feature', properties: { kind: 'route' }, geometry: { type: 'LineString', coordinates } };
    expect(featureLines(feature)).toEqual([coordinates]);
    expect(featureLines({ ...feature, geometry: { type: 'MultiLineString', coordinates: [coordinates] } })).toEqual([coordinates]);
    expect(featureLines({ ...feature, geometry: { type: 'Point', coordinates: [144.958, -37.826] } })).toEqual([]);
  });
});
