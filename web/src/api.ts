import { useCallback, useEffect, useRef, useState } from 'react';
import type { Snapshot, Site, GeoJSON } from './types';
import type { BasemapData } from './basemap';

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const error = await response.json(); if (typeof error.detail === 'string') detail = error.detail; } catch { /* retain status */ }
    throw new Error(detail);
  }
  return response.json();
}

export function usePlatform() {
  const [site, setSite] = useState<Site | null>(null);
  const [geometry, setGeometry] = useState<GeoJSON | null>(null);
  const [basemap, setBasemap] = useState<BasemapData | null>(null);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const lastUpdate = useRef(0);
  const lastRendered = useRef('');
  const apply = useCallback((value: Snapshot) => {
    setSnapshot(value); lastUpdate.current = Date.now(); setConnected(true);
  }, []);
  useEffect(() => {
    let active = true;
    request<BasemapData>('/site/basemap').then(value => { if (active) setBasemap(value); })
      .catch(() => { if (active) setBasemapFailed(true); });
    Promise.all([request<Site>('/site'), request<GeoJSON>('/site/geometry')])
      .then(([s, g]) => { if (active) { setSite(s); setGeometry(g); } })
      .catch(() => { if (active) setError('Site geometry could not be loaded. Check the platform connection and reload.'); });
    request<Snapshot>('/snapshot').then(value => { if (active) apply(value); }).catch(() => { if (active) setConnected(false); });
    const stream = new EventSource('/api/v1/events');
    const receive = (event: MessageEvent) => {
      try { const value = JSON.parse(event.data) as Snapshot; if (active && value.status && value.scenario) apply(value); }
      catch { if (active) setError('An update could not be read. Waiting for the next platform update.'); }
    };
    stream.addEventListener('snapshot', receive);
    stream.onmessage = receive;
    stream.onerror = () => { if (active) setConnected(false); };
    const clock = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() - lastUpdate.current > 15000) setConnected(false);
    }, 1000);
    return () => { active = false; stream.close(); clearInterval(clock); };
  }, [apply]);
  useEffect(() => {
    const reading = snapshot?.sensor;
    if (!reading || reading.readingId === lastRendered.current) return;
    // Two frames give the committed observation a paint opportunity. This is an
    // approximate browser-paint timestamp, not a compositor measurement.
    let secondFrame = 0;
    const frame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        lastRendered.current = reading.readingId;
        void request('/telemetry/render', { readingId: reading.readingId, renderedAt: new Date().toISOString() }).catch(() => undefined);
      });
    });
    return () => { cancelAnimationFrame(frame); cancelAnimationFrame(secondFrame); };
  }, [snapshot?.sensor]);
  const command = useCallback(async (path: string, body: unknown = {}) => {
    setBusy(true); setError('');
    try {
      await request(path, body);
      apply(await request<Snapshot>('/snapshot'));
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'The action could not be completed. Please try again.'); }
    finally { setBusy(false); }
  }, [apply]);
  return { site, geometry, basemap, basemapFailed, snapshot, connected, error, busy, now, command, clearError: () => setError('') };
}
