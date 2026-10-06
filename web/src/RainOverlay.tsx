import type { CSSProperties } from 'react';
import type { Snapshot } from './types';
import { currentRain } from './presentation';

// Stable screen-space drops preserve animation phase across streamed updates.
const DROPS = Array.from({ length: 88 }, (_, i) => ({
  x: (i * 137 + 43) % 1200, y: (i * 193 + 17) % 800,
  delay: -(i * .173 % 1.6),
}));
export default function RainOverlay({ snapshot, connected }: { snapshot: Snapshot | null; connected: boolean }) {
  const intensity = currentRain(snapshot?.weather, connected, snapshot?.scenario.mode);
  if (intensity == null || intensity <= 0) return null;
  const count = Math.min(DROPS.length, Math.round(12 + intensity * .38));
  return <div className={`rain-layer ${snapshot?.scenario.paused && snapshot.scenario.mode === 'simulation' ? 'paused' : ''}`} data-testid="rain-overlay" data-intensity={intensity} aria-hidden="true" style={{ '--rain-opacity': .16 + intensity / 750, '--rain-speed': `${1.65 - intensity / 200}s` } as CSSProperties}>
    <svg viewBox="0 0 1200 800" preserveAspectRatio="none">{DROPS.slice(0, count).map((drop, i) => <line key={i} x1={drop.x} y1={drop.y - 100} x2={drop.x - 6} y2={drop.y - 81} style={{ animationDelay: `${drop.delay}s` }} />)}</svg>
    <span className="rain-map-label">{snapshot?.weather?.source === 'mock' ? 'SIMULATED RAIN' : 'OBSERVED RAIN'} · {intensity} mm/h</span>
  </div>;
}
