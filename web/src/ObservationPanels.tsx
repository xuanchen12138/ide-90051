import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { Sensor, Snapshot } from './types';
import { currentRain, formatTime } from './presentation';

export function WeatherPanel({ snapshot, connected }: { snapshot: Snapshot | null; connected: boolean }) {
  const weather = snapshot?.weather;
  const intensity = currentRain(weather, connected, snapshot?.scenario.mode);
  return <section className="weather-section" aria-labelledby="weather-title">
    <div className="section-heading"><h3 id="weather-title">Rainfall</h3><span className={`source-pill ${weather?.source === 'mock' ? 'simulation' : ''}`} data-testid="rain-source">{weather?.source === 'mock' && snapshot?.scenario.mode === 'simulation' ? 'SIMULATED' : weather?.source === 'physical' ? 'OBSERVED' : 'UNAVAILABLE'}</span></div>
    <div className="rain-reading"><strong data-testid="rain-intensity">{intensity == null ? '—' : intensity}</strong><span>mm/h</span><span className="health-label">{connected ? weather?.freshness ?? 'unavailable' : 'stale'}</span></div>
    <p className="small-note">{snapshot?.scenario.mode === 'normal' ? 'The connected float switches detect water levels, not rainfall. No rain gauge is connected.' : 'Simulated weather context. Water scenario level controls the hazard independently; this is not a rainfall-to-flood model.'}</p>
    {weather?.observedAt && <p className="small-note">Updated {formatTime(weather.observedAt)} Melbourne</p>}
  </section>;
}
export function FloatPanel({ sensor, fresh }: { sensor: Sensor | null | undefined; fresh: boolean }) {
  const physical = sensor?.source === 'physical';
  const level = physical && fresh ? sensor?.floatLevel : null;
  const describe = (value?: boolean | null) => physical && fresh && value != null ? value ? 'Raised · water detected' : 'Lowered · no water at switch' : 'Unknown';
  return <div className="float-panel" data-testid="float-panel">
    <div className="section-heading"><h3>Physical float switches</h3><strong data-testid="float-level">{level == null ? 'Waiting for sensor' : level === -1 ? 'Sensor fault' : `Level ${level} / 2`}</strong></div>
    <dl><div><dt>Lower float</dt><dd data-testid="lower-float">{describe(sensor?.lowerFloat)}</dd></div><div><dt>Upper float</dt><dd data-testid="upper-float">{describe(sensor?.upperFloat)}</dd></div></dl>
    <p className="small-note">Demo mapping: level 0 → 0, level 1 → 60, level 2 → 90 on the water risk scale. These switches do not measure depth in mm.</p>
    {physical && sensor?.sensorUptimeMs != null && <p className="small-note">Device uptime: {Math.floor(sensor.sensorUptimeMs / 1000)}s · received {formatTime(sensor.receivedAt)}</p>}
  </div>;
}
export function RainControls({ snapshot, disabled, command }: { snapshot: Snapshot | null; disabled: boolean; command: (path: string, body: unknown) => Promise<void> }) {
  const [rain, setRain] = useState(snapshot?.weather?.intensityMmPerHour ?? 0);
  const active = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { if (!active.current) setRain(snapshot?.weather?.intensityMmPerHour ?? 0); }, [snapshot?.weather?.intensityMmPerHour]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const adjust = (value: number) => {
    setRain(value); active.current = true;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void command('/scenarios/rainfall', { intensityMmPerHour: value }).finally(() => { active.current = false; }); }, 300);
  };
  return <div className="rain-controls">
    <div className="manual-label"><label htmlFor="rain-slider">Adjust simulated rainfall</label><output htmlFor="rain-slider">{rain} mm/h</output></div>
    <input id="rain-slider" type="range" min="0" max="200" step="5" value={rain} disabled={disabled} onChange={e => adjust(Number(e.target.value))} aria-label="Simulated rainfall intensity" style={{ '--slider-fill': `${rain / 2}%` } as CSSProperties} />
    <div className="range-captions"><span>0 / Dry</span><span>200 mm/h</span></div>
    <p className="small-note">Rain is visual context. Starting or resetting a scenario restores its rain profile.</p>
  </div>;
}
