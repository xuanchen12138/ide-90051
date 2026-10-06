import { useEffect, useMemo, useRef, useState } from 'react';
import type { Feature, GeoJSON, HazardState, Position, Site, Snapshot } from './types';
import { stateStyle } from './presentation';
import Icon from './Icon';
import BasemapLayer from './BasemapLayer';
import { CITY_BOUNDS, createProjection, linePath, onScreen, placeLabels, prepareBasemap } from './basemap';
import type { BasemapData } from './basemap';

type Props = { site: Site; geometry: GeoJSON; basemap: BasemapData | null; basemapFailed: boolean; snapshot: Snapshot | null; connected: boolean };
export function featureLines(feature: Feature): Position[][] {
  if (feature.geometry.type === 'LineString') return [feature.geometry.coordinates as Position[]];
  if (feature.geometry.type === 'MultiLineString' || feature.geometry.type === 'Polygon') return feature.geometry.coordinates as Position[][];
  return [];
}
const GOOGLE_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#f0f1ee' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#747976' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#f8f8f6' }] },
  { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#dfe7d8' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#d2d5d2' }] },
  { featureType: 'road.arterial', elementType: 'geometry', stylers: [{ color: '#b7bdb9' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#8f9791' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#b8d8dd' }] },
  { featureType: 'landscape.man_made', elementType: 'geometry', stylers: [{ color: '#e9eae8' }] },
];
let googleLoader: Promise<void> | null = null;
function loadGoogle() {
  if (window.google?.maps) return Promise.resolve();
  if (!googleLoader) googleLoader = new Promise<void>((resolve, reject) => {
    const callback = '__southbankGoogleReady';
    const target = window as unknown as Record<string, unknown>;
    const timer = window.setTimeout(() => reject(new Error('Street map unavailable')), 15000);
    target[callback] = () => { clearTimeout(timer); resolve(); delete target[callback]; };
    target.gm_authFailure = () => { clearTimeout(timer); window.dispatchEvent(new Event('southbank-map-failed')); reject(new Error('Map authentication failed')); };
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(import.meta.env.VITE_GOOGLE_MAPS_API_KEY)}&loading=async&callback=${callback}&v=weekly`;
    script.async = true;
    script.onerror = () => { clearTimeout(timer); reject(new Error('Street map unavailable')); };
    document.head.appendChild(script);
  });
  return googleLoader;
}
function routeState(snapshot: Snapshot | null, connected: boolean): HazardState {
  return connected ? snapshot?.status.displayState ?? 'UNKNOWN' : 'UNKNOWN';
}
export default function MapView(props: Props) {
  const [renderer, setRenderer] = useState<'offline' | 'google'>('offline');
  const [mapFailure, setMapFailure] = useState(false);
  useEffect(() => {
    let active = true;
    const authenticationFailed = () => { if (active) { setRenderer('offline'); setMapFailure(true); } };
    window.addEventListener('southbank-map-failed', authenticationFailed);
    if (import.meta.env.VITE_GOOGLE_MAPS_API_KEY) loadGoogle().then(() => { if (active) setRenderer('google'); }).catch(() => { if (active) setMapFailure(true); });
    return () => { active = false; window.removeEventListener('southbank-map-failed', authenticationFailed); };
  }, []);
  return <div className="map-container" data-testid="map" data-renderer={renderer} data-basemap={renderer === 'google' ? 'google' : props.basemap ? 'osm' : 'unavailable'}>
    {renderer === 'google' ? <GoogleMap {...props} /> : <OfflineMap {...props} />}
    <div className="map-source"><span className="map-source-dot" />{renderer === 'google' ? 'Google Maps · verified GTFS overlay' : props.basemap ? <><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a><span className="source-detail">· Local snapshot {props.basemap.metadata.osmBaseTimestamp.slice(0, 10)} ·</span><a className="source-detail" href="/api/v1/site/basemap" download="southbank-basemap.geojson">ODbL data</a></> : props.basemapFailed ? 'Street data unavailable · verified GTFS only' : 'Loading local street map…'}{mapFailure && <span>· Google unavailable</span>}</div>
  </div>;
}

function OfflineMap({ site, geometry, basemap, snapshot, connected }: Props) {
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 });
  const [full, setFull] = useState(false);
  const [dragging, setDragging] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  useEffect(() => {
    if (!svg.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width && height) setSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(svg.current); return () => observer.disconnect();
  }, []);
  const pointer = useRef<{ x: number; y: number; originX: number; originY: number } | null>(null);
  const state = routeState(snapshot, connected);
  const style = stateStyle(state);
  const fullImpact = snapshot?.status.impactScope === 'full_route_demo';
  const routes = useMemo(() => geometry.features.filter(f => f.properties.kind === 'route'), [geometry]);
  const local = useMemo(() => geometry.features.filter(f => f.properties.kind === 'local_segment'), [geometry]);
  const bounds = useMemo(() => {
    if (!full) return CITY_BOUNDS;
    const points = routes.flatMap(f => featureLines(f).flat());
    if (!points.length) return site.focusBounds;
    return { north: Math.max(...points.map(p => p[1])), south: Math.min(...points.map(p => p[1])), east: Math.max(...points.map(p => p[0])), west: Math.min(...points.map(p => p[0])) };
  }, [full, routes, site.focusBounds]);
  const projection = useMemo(() => createProjection(bounds, size), [bounds, size]);
  const { project } = projection;
  const prepared = useMemo(() => basemap ? prepareBasemap(basemap, projection) : [], [basemap, projection]);
  const path = (line: Position[]) => linePath(line, project);
  const routePaths = routes.flatMap(f => featureLines(f)).map(path);
  const localPaths = local.flatMap(f => featureLines(f)).map(path);
  const center = project([site.center.longitude, site.center.latitude]);
  const siteScreen = onScreen(center, view, size);
  const calloutX = Math.max(10, Math.min(size.width - (size.width < 600 ? 95 : 9) - 187, siteScreen[0] + (size.width < 600 ? -93 : 25)));
  const calloutY = siteScreen[1] + 22;
  const labels = useMemo(() => full ? [] : placeLabels(prepared, view, size, [
    [0, 0, size.width < 600 ? 285 : 360, size.width < 600 ? 115 : 145],
    [0, size.height - (size.width < 600 ? 120 : 175), size.width < 600 ? 305 : 485, size.height],
    [size.width - (size.width < 600 ? 88 : 155), size.height - (size.width < 600 ? 224 : 375), size.width, size.height - (size.width < 600 ? 78 : 145)],
    [size.width - 78, 0, size.width, 90],
    [calloutX - 5, calloutY - 5, calloutX + 192, calloutY + 49],
  ], basemap ? [...project([basemap.metadata.bounds.west, basemap.metadata.bounds.north]), ...project([basemap.metadata.bounds.east, basemap.metadata.bounds.south])] : undefined), [prepared, view, size, full, calloutX, calloutY, basemap, project]);
  const waterLevel = connected && snapshot?.status.dataFreshness.sensor === 'fresh' && state !== 'UNKNOWN' ? snapshot?.sensor?.scenarioLevel ?? 0 : 0;
  const floodPath = site.conceptualFlood?.coordinates?.map(path).join(' Z ') + ' Z';
  const zoom = (delta: number) => setView(v => ({ ...v, zoom: Math.min(8, Math.max(.45, v.zoom * delta)) }));
  useEffect(() => {
    const element = svg.current; if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      const x = event.clientX - rect.left - size.width / 2, y = event.clientY - rect.top - size.height / 2;
      setView(v => { const next = Math.min(8, Math.max(.45, v.zoom * Math.exp(-event.deltaY * .002))); const ratio = next / v.zoom; return { zoom: next, x: x - (x - v.x) * ratio, y: y - (y - v.y) * ratio }; });
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [size]);
  const reset = () => { setFull(false); setView({ x: 0, y: 0, zoom: 1 }); };
  const showFull = () => { setFull(v => !v); setView({ x: 0, y: 0, zoom: 1 }); };
  const metersPerPixel = 1 / (projection.pixelsPerMeter * view.zoom);
  const scaleMeters = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000].filter(m => m / metersPerPixel <= 100).at(-1) ?? 10;
  const routeStroke = (paths: string[], isLocal: boolean) => paths.map((d, i) => <g key={i}>
    <path d={d} className="route-halo" strokeWidth={isLocal ? 16 : 9} />
    {state === 'WATCH' && (isLocal || fullImpact) && <path d={d} className="route-halo watch-outline" stroke="#6b5816" strokeWidth={isLocal ? 13 : 8} style={{ stroke: '#6b5816', strokeOpacity: .8 }} />}
    <path d={d} className={`route-stroke ${state === 'CRITICAL' && (isLocal || fullImpact) ? 'critical-route' : ''}`} data-risk={isLocal || fullImpact ? state : 'context'} stroke={isLocal || fullImpact ? style.color : '#8d9990'} strokeWidth={isLocal ? 9 : 4} strokeDasharray={state === 'UNKNOWN' ? '10 8' : undefined} opacity={isLocal || fullImpact ? 1 : .5} />
  </g>);
  return <>
    <svg ref={svg} viewBox={`0 0 ${size.width} ${size.height}`} className={`offline-map ${dragging ? 'dragging' : ''}`} role="img" aria-label="Verified Route 58 geometry and City Road Kings Way Stop 116 on a detailed Melbourne street map with buildings, bridges and the Yarra River. Pan with arrow keys; zoom with plus and minus." tabIndex={0}
      onKeyDown={e => { const shifts: Record<string, [number, number]> = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }; if (e.key in shifts) { e.preventDefault(); const [x, y] = shifts[e.key]; setView(v => ({ ...v, x: v.x + x, y: v.y + y })); } else if (['+', '=', '-'].includes(e.key)) { e.preventDefault(); zoom(e.key === '-' ? 1 / 1.25 : 1.25); } else if (e.key === 'Home') reset(); }}
      onPointerDown={e => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); pointer.current = { x: e.clientX, y: e.clientY, originX: view.x, originY: view.y }; setDragging(true); }}
      onPointerMove={e => { if (!pointer.current || !svg.current) return; const p = pointer.current; setView(v => ({ ...v, x: p.originX + e.clientX - p.x, y: p.originY + e.clientY - p.y })); }}
      onPointerUp={() => { pointer.current = null; setDragging(false); }} onPointerCancel={() => { pointer.current = null; setDragging(false); }}>
      <defs>
        <pattern id="water-lines" width="34" height="22" patternUnits="userSpaceOnUse"><path d="M-10 11 Q0 2 10 11 T30 11 T50 11" stroke="#5997ac" strokeWidth="1.4" fill="none" opacity=".55" /></pattern>
        <radialGradient id="water-fill"><stop offset="0" stopColor="#8cc9d8" stopOpacity=".55" /><stop offset="1" stopColor="#8cc9d8" stopOpacity=".16" /></radialGradient>
      </defs>
      <g transform={`translate(${size.width / 2 + view.x}, ${size.height / 2 + view.y}) scale(${view.zoom}) translate(${-size.width / 2},${-size.height / 2})`}>
        {basemap ? <BasemapLayer data={basemap} items={prepared} projection={projection} view={view} size={size} /> : [0, 1, 2, 3, 4].map(i => {
          const lon = bounds.west + (bounds.east - bounds.west) * i / 4;
          const lat = bounds.south + (bounds.north - bounds.south) * i / 4;
          const [x] = project([lon, lat]); const [, y] = project([lon, lat]);
          return <g key={i} className="coordinate-grid"><line x1={x} x2={x} y1="-3000" y2="3000" /><line y1={y} y2={y} x1="-3000" x2="3000" /><text x={x + 8} y={765}>{lon.toFixed(4)}°E</text><text x={40} y={y - 9}>{Math.abs(lat).toFixed(4)}°S</text></g>;
        })}
        {waterLevel > 0 && floodPath && <g className={snapshot?.scenario.paused ? 'water-overlay paused' : 'water-overlay'} opacity={Math.min(.95, .12 + waterLevel / 100)} transform={`translate(${center[0]},${center[1]}) scale(${.3 + waterLevel / 95}) translate(${-center[0]},${-center[1]})`} data-testid="flood-overlay">
          <path d={floodPath} fill="url(#water-fill)" stroke="#7eb6c6" strokeWidth="1.2" />
          <path className="water-texture" d={floodPath} fill="url(#water-lines)" />
          <path className="water-contour" d={floodPath} fill="none" stroke="#7eb6c6" strokeWidth="2" />
        </g>}
        {routeStroke(routePaths, false)}{routeStroke(localPaths, true)}
        {(connected ? snapshot?.transport.vehicles.filter(v => v.freshness === 'fresh') ?? [] : []).map((vehicle, i) => {
          const [x, y] = project([vehicle.longitude, vehicle.latitude]);
          return <g key={vehicle.vehicleId ?? i} transform={`translate(${x},${y})`} className="vehicle-marker"><title>{snapshot?.transport.source === 'fixture' ? 'Fixture' : 'Observed'} tram {vehicle.vehicleId ?? ''}{vehicle.observedAt ? ` · ${vehicle.observedAt}` : ''}</title><rect x="-8" y="-11" width="16" height="22" rx="5" /><path d="M-4-5h8M-4 5h8" /></g>;
        })}
        {site.stops.map((stop, i) => {
          const [x, y] = project([stop.longitude, stop.latitude]);
          return <g key={stop.stopId} className="stop-marker" data-testid="stop-marker"><circle cx={x} cy={y} r={8 / view.zoom} fill="white" stroke={style.color} strokeWidth={3 / view.zoom} /><circle cx={x} cy={y} r={3 / view.zoom} fill="#24282c" /><title>{stop.name} · GTFS {stop.stopId} · platform {i + 1}</title></g>;
        })}
      </g>
      <g className="map-labels">{labels.map(label => <text key={label.id} className={`label-${label.kind}`} data-map-label={label.kind} x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" transform={label.angle ? `rotate(${label.angle},${label.x},${label.y})` : undefined}>{label.name}</text>)}</g>
      {!full && siteScreen[0] > -20 && siteScreen[0] < size.width + 20 && siteScreen[1] > 0 && siteScreen[1] < size.height - 80 && <g className="site-callout">
        <line x1={siteScreen[0] + 8} y1={siteScreen[1] + 8} x2={calloutX + 10} y2={calloutY + 6} />
        <g transform={`translate(${calloutX},${calloutY})`}><rect width="187" height="45" rx="5" /><text x="11" y="18" className="stop-title">City Rd / Kings Way</text><text x="11" y="34" className="stop-caption">58 · STOP 116 · BOTH DIRECTIONS</text></g>
      </g>}
    </svg>
    <MapControls onReset={reset} onZoom={zoom} onFull={showFull} full={full} />
    <div className="north-arrow" aria-label="North is up"><span>N</span><svg width="17" height="25" viewBox="0 0 17 25" aria-hidden="true"><path d="M8.5 0 17 23 8.5 18 0 23Z" fill="#5c645d" /><path d="M8.5 0v18L0 23Z" fill="#b2b8b3" /></svg></div>
    <div className="map-keyboard-hint">Drag to pan <span>·</span> Scroll to explore buildings</div>
    <div className="map-scale" aria-label={`Map scale ${scaleMeters} metres`}>{scaleMeters >= 1000 ? `${scaleMeters / 1000} km` : `${scaleMeters} m`}<i style={{ width: scaleMeters / metersPerPixel }} /></div>
    {full && <div className="coverage-note">Street detail covers central Melbourne.<br />Full Route 58 follows verified GTFS geometry.</div>}
  </>;
}

function MapControls({ onReset, onZoom, onFull, full }: { onReset: () => void; onZoom: (factor: number) => void; onFull: () => void; full: boolean }) {
  return <div className="map-controls"><button className="map-return" onClick={onReset}><Icon name="target" />Return to Stop 116</button><button className="map-full" onClick={onFull} aria-pressed={full}>{full ? 'Local view' : 'View full route'}</button><div className="zoom-buttons"><button onClick={() => onZoom(1.25)} aria-label="Zoom in"><Icon name="plus" /></button><button onClick={() => onZoom(1 / 1.25)} aria-label="Zoom out"><Icon name="minus" /></button></div></div>;
}

function GoogleMap({ site, geometry, snapshot, connected }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<google.maps.Map | null>(null);
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!container.current) return;
    const mapId = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID;
    const instance = new google.maps.Map(container.current, {
      center: { lat: site.center.latitude, lng: site.center.longitude }, zoom: 16,
      mapTypeControl: false, streetViewControl: false, fullscreenControl: false, zoomControl: false,
      clickableIcons: false, gestureHandling: 'greedy', tilt: 0,
      ...(mapId ? { mapId, renderingType: google.maps.RenderingType.VECTOR, colorScheme: google.maps.ColorScheme.LIGHT } : { styles: GOOGLE_STYLE }),
    });
    instance.fitBounds(CITY_BOUNDS, 70); setMap(instance);
    return () => { google.maps.event.clearInstanceListeners(instance); };
  }, [site]);
  useEffect(() => {
    if (!map) return;
    const state = routeState(snapshot, connected); const color = stateStyle(state).color;
    const fullImpact = snapshot?.status.impactScope === 'full_route_demo';
    const overlays: { setMap: (map: google.maps.Map | null) => void }[] = [];
    const pulseLines: google.maps.Polyline[] = [];
    const level = connected && state !== 'UNKNOWN' && snapshot?.status.dataFreshness.sensor === 'fresh' ? snapshot?.sensor?.scenarioLevel ?? 0 : 0;
    if (level > 0 && site.conceptualFlood) {
      const scale = .3 + level / 95;
      const coords = site.conceptualFlood.coordinates[0].map(([lng, lat]) => ({ lat: site.center.latitude + (lat - site.center.latitude) * scale, lng: site.center.longitude + (lng - site.center.longitude) * scale }));
      overlays.push(new google.maps.Polygon({ map, paths: coords, fillColor: '#8cc9d8', fillOpacity: .08 + level / 260, strokeColor: '#7eb6c6', strokeOpacity: .5, strokeWeight: 2, zIndex: 1, clickable: false }));
      class Ripple extends google.maps.OverlayView {
        element: HTMLDivElement | null = null;
        onAdd() {
          this.element = document.createElement('div'); this.element.className = `google-water-ripple ${snapshot?.scenario.paused ? 'paused' : ''}`;
          this.element.innerHTML = '<i></i><i></i><i></i>';
          this.element.querySelectorAll('i').forEach((ring, index) => { ring.style.animationDelay = `${-((Date.now() + index * 650) % 2000) / 1000}s`; });
          this.getPanes()?.overlayLayer.appendChild(this.element);
        }
        draw() {
          if (!this.element) return;
          const projection = this.getProjection();
          const pixels = coords.map(p => projection.fromLatLngToDivPixel(new google.maps.LatLng(p))!);
          const minX = Math.min(...pixels.map(p => p.x)), minY = Math.min(...pixels.map(p => p.y));
          const width = Math.max(...pixels.map(p => p.x)) - minX, height = Math.max(...pixels.map(p => p.y)) - minY;
          Object.assign(this.element.style, { left: `${minX}px`, top: `${minY}px`, width: `${width}px`, height: `${height}px`, opacity: `${level / 100}`, clipPath: `polygon(${pixels.map(p => `${(p.x - minX) / width * 100}% ${(p.y - minY) / height * 100}%`).join(',')})` });
        }
        onRemove() { this.element?.remove(); }
      }
      const ripple = new Ripple(); ripple.setMap(map); overlays.push(ripple);
    }
    geometry.features.filter(f => ['route', 'local_segment'].includes(f.properties.kind)).forEach(feature => {
      const local = feature.properties.kind === 'local_segment';
      featureLines(feature).forEach(line => {
        const path = line.map(([lng, lat]) => ({ lat, lng }));
        overlays.push(new google.maps.Polyline({ map, path, strokeColor: '#ffffff', strokeOpacity: .85, strokeWeight: local ? 15 : 7, zIndex: local ? 4 : 2, clickable: false }));
        if (state === 'WATCH' && (local || fullImpact)) overlays.push(new google.maps.Polyline({ map, path, strokeColor: '#6b5816', strokeOpacity: .7, strokeWeight: local ? 12 : 6, zIndex: local ? 5 : 3, clickable: false }));
        const route = new google.maps.Polyline({ map, path, strokeColor: local || fullImpact ? color : '#829386', strokeOpacity: state === 'UNKNOWN' ? 0 : local || fullImpact ? 1 : .5, strokeWeight: local ? 9 : 4, zIndex: local ? 6 : 3, clickable: false, ...(state === 'UNKNOWN' ? { icons: [{ icon: { path: 'M 0,-1 0,1', strokeColor: color, strokeOpacity: 1, strokeWeight: local ? 8 : 3, scale: 3 }, offset: '0', repeat: '18px' }] } : {}) });
        overlays.push(route);
        if (state === 'CRITICAL' && (local || fullImpact)) pulseLines.push(route);
      });
    });
    site.stops.forEach(stop => {
      overlays.push(new google.maps.Marker({ map, position: { lat: stop.latitude, lng: stop.longitude }, title: `${stop.name} · GTFS ${stop.stopId}`, zIndex: 10, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 11, fillColor: '#ffffff', fillOpacity: 1, strokeColor: color, strokeWeight: 4 } }));
      overlays.push(new google.maps.Marker({ map, position: { lat: stop.latitude, lng: stop.longitude }, title: stop.name, zIndex: 11, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 4, fillColor: '#24282c', fillOpacity: 1, strokeWeight: 0 } }));
    });
    (connected ? snapshot?.transport.vehicles.filter(v => v.freshness === 'fresh') ?? [] : []).forEach(vehicle => overlays.push(new google.maps.Marker({ map, position: { lat: vehicle.latitude, lng: vehicle.longitude }, title: `${snapshot?.transport.source === 'fixture' ? 'Fixture' : 'Observed'} tram ${vehicle.vehicleId ?? ''} · ${vehicle.observedAt ?? 'Observation time unavailable'}`, zIndex: 9, icon: { path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW, scale: 4, fillColor: '#4a5351', fillOpacity: 1, strokeColor: 'white', strokeWeight: 1.5, rotation: vehicle.bearing ?? 0 } })));
    const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let pulseTimer: number | undefined;
    const configurePulse = () => {
      if (pulseTimer !== undefined) clearInterval(pulseTimer);
      pulseTimer = undefined;
      pulseLines.forEach(line => line.setOptions({ strokeOpacity: 1 }));
      if (pulseLines.length && !motionPreference.matches && !snapshot?.scenario.paused) {
        // The absolute clock preserves the 2-second phase across sensor updates.
        pulseTimer = window.setInterval(() => {
          const opacity = .88 + .12 * Math.cos(Date.now() / 2000 * Math.PI * 2);
          pulseLines.forEach(line => line.setOptions({ strokeOpacity: opacity }));
        }, 100);
      }
    };
    configurePulse(); motionPreference.addEventListener('change', configurePulse);
    return () => { if (pulseTimer !== undefined) clearInterval(pulseTimer); motionPreference.removeEventListener('change', configurePulse); overlays.forEach(overlay => overlay.setMap(null)); };
  }, [map, geometry, site, snapshot, connected]);
  const reset = () => { map?.fitBounds(CITY_BOUNDS, 70); setFull(false); };
  const toggleFull = () => {
    if (full) return reset();
    const bounds = new google.maps.LatLngBounds(); geometry.features.filter(f => f.properties.kind === 'route').flatMap(featureLines).flat().forEach(([lng, lat]) => bounds.extend({ lat, lng }));
    map?.fitBounds(bounds, 50); setFull(true);
  };
  return <><div ref={container} className="google-map" role="region" aria-label="Google street map with verified Route 58 and Stop 116 overlays" /><MapControls onReset={reset} onFull={toggleFull} full={full} onZoom={factor => map?.setZoom((map.getZoom() ?? 16) + (factor > 1 ? 1 : -1))} /></>;
}

