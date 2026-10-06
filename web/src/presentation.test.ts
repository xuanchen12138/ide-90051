import { describe, expect, it } from 'vitest';
import { delayLabel, formatAge, formatTime, SCENARIOS, stateStyle, currentRain, vehicleTitle, transportSourceLabel } from './presentation';
import { featureLines } from './MapView';
import type { Feature, Weather } from './types';

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

describe('rain and tram provenance boundaries', () => {
  const weather: Weather = { intensityMmPerHour: 80, source: 'mock', observedAt: '2026-10-06T00:00:00Z', freshness: 'fresh' };
  it('shows rain only for a fresh connected observation in its allowed operating mode', () => {
    expect(currentRain(weather, true, 'simulation')).toBe(80);
    expect(currentRain({ ...weather, intensityMmPerHour: 0 }, true, 'simulation')).toBe(0);
    expect(currentRain(weather, false, 'simulation')).toBeNull();
    expect(currentRain(weather, true, 'normal')).toBeNull();
    expect(currentRain({ ...weather, freshness: 'stale' }, true, 'simulation')).toBeNull();
    expect(currentRain({ ...weather, source: 'unavailable' }, true, 'simulation')).toBeNull();
    for (const value of [null, NaN, -1, 201]) expect(currentRain({ ...weather, intensityMmPerHour: value }, true, 'simulation')).toBeNull();
  });
  it('labels each marker by its record source even in a mixed transport response', () => {
    const vehicle = { vehicleId: 'DEMO-58-1', latitude: -37.82, longitude: 144.96, source: 'mock' };
    expect(vehicleTitle(vehicle, 'mixed')).toBe('Mock demo tram DEMO-58-1');
    expect(vehicleTitle({ ...vehicle, vehicleId: 'real-1', source: 'transport-victoria' }, 'mixed')).toBe('Observed tram real-1');
    expect(vehicleTitle({ ...vehicle, source: undefined }, 'mixed')).toContain('Unconfirmed source');
    expect(transportSourceLabel('mixed')).toContain('Live + mock');
    expect(transportSourceLabel('mock')).toContain('Mock');
  });
});
