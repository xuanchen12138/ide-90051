import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { usePlatform } from './api';
import { delayLabel, formatAge, formatTime, humanize, SCENARIOS, STATES, stateStyle, transportSourceLabel } from './presentation';
import { FloatPanel, RainControls, WeatherPanel } from './ObservationPanels';
import RainOverlay from './RainOverlay';
import type { Feed, HazardState, Snapshot } from './types';
import Icon from './Icon';
import MapView from './MapView';

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Eases the displayed number toward the latest observation (≈450 ms). The
// final frame always lands exactly on the backend value.
function useAnimatedNumber(target: number | null) {
  const [shown, setShown] = useState<number | null>(target);
  const frame = useRef(0);
  useEffect(() => {
    cancelAnimationFrame(frame.current);
    if (target == null || shown == null || reducedMotion()) { setShown(target); return; }
    const from = shown, start = performance.now(), duration = 450;
    const step = (time: number) => {
      const t = Math.min(1, (time - start) / duration), eased = 1 - Math.pow(1 - t, 3);
      setShown(t >= 1 ? target : from + (target - from) * eased);
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps
  return shown;
}

export default function App() {
  const { site, geometry, basemap, basemapFailed, snapshot, connected, busy, error, now, command, clearError } = usePlatform();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState('water-rising');
  const [manual, setManual] = useState(0);
  const [intro, setIntro] = useState(true);
  const manualActive = useRef(false);
  const manualTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const status = snapshot?.status;
  const state: HazardState = connected ? status?.hazardState ?? 'UNKNOWN' : 'UNKNOWN';
  const appearance = stateStyle(state);
  const simulation = snapshot?.scenario.mode !== 'normal';
  const sensor = snapshot?.sensor;
  const disabled = busy || !connected;
  const serviceState = connected ? status?.serviceState ?? 'UNKNOWN' : 'UNKNOWN';
  const sensorFreshness = connected ? status?.dataFreshness.sensor ?? 'unavailable' : 'stale';
  const transportFreshness = connected ? status?.dataFreshness.transport ?? 'unavailable' : 'stale';
  const transport = snapshot?.transport;
  const transportSource = transport?.source ?? 'transport-victoria';
  const mockTrams = connected && (transportSource === 'mock' || transportSource === 'mixed' || snapshot?.scenario.transportMode === 'mock');
  const showLiveFeeds = Boolean(transport?.liveFeeds) && (transport?.fallback || mockTrams) && transportSource !== 'fixture';
  useEffect(() => {
    if (!manualActive.current) setManual(snapshot?.sensor?.scenarioLevel ?? 0);
  }, [snapshot?.sensor?.scenarioLevel]);
  useEffect(() => () => { if (manualTimer.current) clearTimeout(manualTimer.current); }, []);
  useEffect(() => { document.title = `${appearance.label} — Southbank Flood watch`; }, [appearance.label]);
  // The entrance choreography runs once; afterwards only state transitions animate.
  useEffect(() => { const timer = window.setTimeout(() => setIntro(false), 2600); return () => clearTimeout(timer); }, []);
  const adjustManual = (value: number) => {
    setManual(value); manualActive.current = true;
    if (manualTimer.current) clearTimeout(manualTimer.current);
    manualTimer.current = setTimeout(() => {
      void command('/scenarios/manual', { level: value }).finally(() => { manualActive.current = false; });
    }, 300);
  };
  const levelValue = connected && sensor?.scenarioLevel != null ? Math.round(sensor.scenarioLevel) : null;
  const animatedLevel = useAnimatedNumber(levelValue);
  const sourceName = sensor?.source === 'mock' ? 'Simulated sensor' : sensor?.source === 'physical' ? 'Physical sensor' : 'No sensor';
  const timeline = [...(snapshot?.timeline ?? [])].reverse().slice(0, 4);
  const freshVehicles = connected ? snapshot?.transport.vehicles.filter(v => v.freshness === 'fresh') ?? [] : [];
  const freshTrips = connected ? snapshot?.transport.tripUpdates.filter(t => t.freshness === 'fresh') ?? [] : [];
  const latestTrip = freshTrips[0];
  const trend = sensor?.trend === 'rising' ? ['trend-up', 'Rising'] : sensor?.trend === 'falling' ? ['trend-down', 'Receding'] : sensor?.trend === 'steady' ? ['trend-flat', 'Steady'] : ['question', 'Unknown trend'];
  const paused = snapshot?.scenario.paused;

  const vars = { '--risk': appearance.color, '--risk-ink': appearance.ink, '--risk-soft': appearance.soft } as CSSProperties;

  return <div className={`app ${sheetOpen ? 'sheet-open' : ''} ${intro ? 'intro' : ''}`} data-state={state} style={vars}>
    <a href="#status-panel" className="skip-link">Skip to current status</a>

    <header className="topbar">
      <a href="/" className="brand" aria-label="Southbank Flood watch home"><span className="brand-mark"><Icon name="water" size={18} strokeWidth={2} /></span><span className="brand-text">Southbank<span className="brand-sub">Flood watch</span></span></a>
      <div className="topbar-context" aria-label="Data health">
        <span className="health-chip" title="Water-level sensor freshness"><i className={`freshness-dot ${sensorFreshness}`} />Sensor<b>{sensorFreshness}</b></span>
        <span className="health-chip" title={mockTrams ? 'Tram data is a labelled mock demonstration' : 'Transport Victoria feed freshness'}><i className={`freshness-dot ${mockTrams ? 'mock' : transportFreshness}`} />Transport<b>{mockTrams ? 'mock' : transportFreshness}</b></span>
      </div>
      <div className="topbar-right">
        <time className="clock" dateTime={new Date(now).toISOString()} title="Melbourne local time"><span>{formatTime(new Date(now).toISOString())}</span><small>MEL</small></time>
        <span className={`connection ${connected ? 'connected' : ''}`} title={connected ? 'Receiving platform updates' : 'Reconnecting; any retained data is an old snapshot'}><i className="signal" aria-hidden="true"><b /><b /><b /></i>{connected ? 'Connected' : snapshot ? 'Disconnected' : 'Connecting'}</span>
        <div className="mode-switch" role="group" aria-label="Operating mode">
          <button aria-pressed={!simulation} disabled={disabled} onClick={() => void command('/settings', { mode: 'normal' })}>Normal operation</button>
          <button aria-pressed={simulation} disabled={disabled} onClick={() => void command('/settings', { mode: 'simulation' })}><span className="tiny-diamond" />Simulation mode</button>
        </div>
      </div>
    </header>

    <main className="workspace">
      <section className="map-stage" aria-label="Site map">
        <div className="map-heading reveal" style={{ '--i': 1 } as CSSProperties}>
          <div className="eyebrow"><span className="route-badge">58</span><span>Local flood monitoring</span></div>
          <h1>Southbank, Melbourne</h1>
          <p>City Rd / Kings Way <span>—</span> Stop 116{site && <small>{Math.abs(site.center.latitude).toFixed(4)}° S · {site.center.longitude.toFixed(4)}° E</small>}</p>
        </div>
        {site && geometry ? <MapView site={site} geometry={geometry} basemap={basemap} basemapFailed={basemapFailed} snapshot={snapshot} connected={connected} intro={intro} /> : <div className="map-loading"><span className="loading-ring" /><strong>Locating the tram corridor</strong><span>Loading verified Transport Victoria geometry</span></div>}
        <RainOverlay snapshot={snapshot} connected={connected} />
        {!connected && snapshot && <div className="disconnect-banner" role="alert"><Icon name="info" /><span><strong>Connection lost.</strong> Last snapshot {formatTime(status?.evaluatedAt)} Melbourne. Reconnecting…</span></div>}
        <div className="map-legend reveal" style={{ '--i': 4 } as CSSProperties}>
          <span className="legend-title">Hazard state</span>
          <div className="legend-states">{Object.entries(STATES).map(([key, value]) => <span key={key} className={state === key ? 'legend-item active' : 'legend-item'}><i style={{ background: value.color }} className={key === 'UNKNOWN' ? 'dashed' : key === 'WATCH' ? 'outlined' : ''} />{value.label}</span>)}</div>
          <span className="water-legend"><i />Conceptual flood extent<span className="legend-note">· illustrative only</span></span>
        </div>
      </section>

      <aside className="status-panel" id="status-panel" aria-label="Stop status and scenario controls">
        <span className="state-band" aria-hidden="true" />
        <button className="sheet-toggle" onClick={() => setSheetOpen(v => !v)} aria-expanded={sheetOpen} aria-controls="panel-body"><span className="sheet-handle" /><span>{sheetOpen ? 'Hide details' : 'View details & controls'}</span><Icon name="chevron" /></button>
        <div className="status-overview">
          <span className="state-flash" key={`flash-${state}`} aria-hidden="true" />
          <div className="section-topline reveal" style={{ '--i': 2 } as CSSProperties}><span className="eyebrow">Local water risk</span><span className={`source-pill ${simulation ? 'simulation' : ''}`}>{simulation ? 'Simulated' : 'Observation'}</span></div>
          <div className="hazard-headline reveal" style={{ '--i': 3 } as CSSProperties} aria-live="polite" aria-atomic="true">
            <h2 data-testid="hazard-state" key={state} className="state-word">{appearance.label}</h2>
            <span className="hazard-symbol" aria-hidden="true"><Icon name={appearance.icon} size={22} strokeWidth={2} /></span>
          </div>
          <p className="hazard-summary reveal" style={{ '--i': 4 } as CSSProperties}>{!connected ? snapshot ? 'Live updates interrupted. The current risk is unknown.' : 'Waiting for the first platform observation.' : simulation ? appearance.summary : appearance.summary.replace('simulated ', '')}</p>
          <div className="always-visible-sources reveal" style={{ '--i': 5 } as CSSProperties}><span><i className={`freshness-dot ${sensorFreshness}`} />{sourceName}</span><time dateTime={status?.evaluatedAt} title={status?.evaluatedAt}>Updated {formatTime(status?.evaluatedAt)}<span className="time-zone"> Melbourne</span></time></div>
          <div className="state-pair reveal" style={{ '--i': 6 } as CSSProperties}>
            <div className="state-tile hazard"><span className="mini-label">Hazard · {simulation ? 'simulated' : 'observed'}</span><strong><i />{appearance.label}</strong></div>
            <div className={`state-tile service ${serviceState.toLowerCase()}`}><span className="mini-label">Service · {snapshot?.transport.source === 'fixture' ? 'fixture' : 'observed'}</span><strong><i />{humanize(serviceState)}</strong></div>
          </div>
          <div className="mobile-service-summary"><span>Tram: {humanize(serviceState)}</span><span>{snapshot?.transport.source === 'fixture' ? 'Synthetic fixture' : 'Transport Victoria'} · {transportFreshness}</span></div>
        </div>

        <div className="panel-body" id="panel-body">
          {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={clearError} aria-label="Dismiss error"><Icon name="close" size={16} /></button></div>}
          {simulation && <div className="simulation-notice"><span className="tiny-diamond" /><span>Simulated impact — not an official service status.</span></div>}

          <section className="sensor-section" aria-labelledby="sensor-title">
            <div className="measurement">
              <div><h3 id="sensor-title">Water scenario level</h3><div className="level-reading"><strong data-testid="scenario-level">{levelValue == null ? '—' : Math.round(animatedLevel ?? levelValue)}</strong><span>/ 100</span></div></div>
              <div className={`trend ${sensor?.trend ?? ''}`}><Icon name={trend[0]} size={15} strokeWidth={1.8} /><span>{trend[1]}</span></div>
            </div>
            <div className="level-scale" aria-hidden="true">
              <div className="level-track"><span className="level-fill" style={{ width: `${levelValue ?? 0}%` }} /><span className="level-marker" style={{ left: `${levelValue ?? 0}%` }} /></div>
              <div className="level-ticks">{Array.from({ length: 11 }, (_, i) => <i key={i} className={i % 5 === 0 ? 'major' : ''} />)}</div>
              <div className="level-captions"><span>0</span><span>50</span><span>100</span></div>
            </div>
            <p className="small-note">Unitless demonstration scale · not measured depth</p>
            <div className="reason-block"><span className="mini-label">Why this state</span><p>{!connected ? 'Current risk cannot be confirmed because platform updates are interrupted. Any retained observations below belong to the last received snapshot.' : status?.reasons?.length ? status.reasons.join(' ') : 'The platform needs a valid, recent water observation to evaluate this location.'}</p>{connected && status?.recommendedAction && <p className="recommended-action"><Icon name="arrow" size={13} />{status.recommendedAction}</p>}</div>
            {!simulation && <FloatPanel sensor={sensor} fresh={connected && status?.dataFreshness.sensor === 'fresh'} />}
          </section>

          <WeatherPanel snapshot={snapshot} connected={connected} />

          <section className="transport-section" aria-labelledby="transport-title">
            <div className="section-heading"><h3 id="transport-title"><Icon name="tram" />Tram service</h3><span className={`service-state ${serviceState.toLowerCase()}`} data-testid="service-state">{humanize(serviceState)}</span></div>
            <div className="source-line"><span>{transportSourceLabel(transportSource).toUpperCase()}</span><span className={`health-label ${transportFreshness}`}>{connected ? status?.dataFreshness.transport ?? 'unavailable' : snapshot ? 'stale' : 'unavailable'}</span></div>
            {connected && transport?.fallback && <div className="transport-fallback"><strong>Live feed fallback active</strong><p>{transport.fallbackReason ?? 'Live Transport Victoria feeds are stale or unavailable.'}</p><span>Replaced feeds carry mock records labelled on every marker; nothing here is an official service status.</span></div>}
            {mockTrams && <p className="mock-transport-note"><span className="tiny-diamond" />Mock tram demo · moving positions and trip timings are simulated, not real services.</p>}
            {snapshot?.transport.alerts?.length ? <div className="alerts">{snapshot.transport.alerts.slice(0, 3).map((alert, i) => <article className={`service-alert ${alert.source === 'fixture' || snapshot.transport.source === 'fixture' ? 'fixture' : 'official'}`} key={alert.id ?? i}><span className="alert-provenance">{!connected && 'LAST RECEIVED · '}{alert.source === 'fixture' || snapshot.transport.source === 'fixture' ? 'SYNTHETIC ALERT · TEST ONLY' : 'OFFICIAL SERVICE ALERT'}</span><strong>{alert.header}</strong>{alert.description && <p>{alert.description}</p>}<time>{alert.activeFrom ? `From ${formatTime(alert.activeFrom)}` : `Feed ${formatTime(snapshot.transport.feeds?.serviceAlerts?.feedTimestamp)}`}</time></article>)}</div> : <p className="transport-summary">{connected && snapshot?.transport.feeds?.serviceAlerts?.freshness === 'fresh' ? 'No relevant service alert in the current feed.' : 'Current service conditions cannot be confirmed.'}</p>}
            <div className="transport-stats"><span><strong>{connected ? freshVehicles.length : '—'}</strong>{mockTrams ? 'tram positions · mock' : 'fresh tram positions'}</span><span><strong>{connected ? freshTrips.length : '—'}</strong>{mockTrams ? 'trip updates · mock' : 'fresh trip updates'}</span></div>
            {latestTrip ? <p className="small-note">Latest trip: {latestTrip.scheduleRelationship === 'CANCELED' ? 'Canceled in the transport feed' : latestTrip.stopScheduleRelationship === 'SKIPPED' ? 'This stop is skipped' : latestTrip.stopScheduleRelationship === 'NO_DATA' ? 'No stop prediction available' : delayLabel(latestTrip.arrivalDelaySeconds ?? latestTrip.departureDelaySeconds ?? latestTrip.tripDelaySeconds)}. Cause is unconfirmed.</p> : null}
            <details className="data-details"><summary><span>Data sources &amp; timestamps</span><Icon name="chevron" size={14} /></summary><div className="feed-list"><div className="feed-row"><div><strong>{sourceName}</strong><span>Observed {formatTime(sensor?.observedAt)} · {formatAge(sensor?.observedAt, now)}</span><span>Received {formatTime(sensor?.receivedAt)} · quality {sensor?.quality ?? 'unknown'}</span></div><span className={`health-label ${sensorFreshness}`}>{connected ? status?.dataFreshness.sensor ?? 'unavailable' : 'stale'}</span></div>{(['vehiclePositions', 'tripUpdates', 'serviceAlerts'] as const).map(key => <FeedRow key={key} name={{ vehiclePositions: 'Vehicle positions', tripUpdates: 'Trip updates', serviceAlerts: 'Service alerts' }[key]} feed={transport?.feeds?.[key]} connected={connected} />)}{showLiveFeeds && <><div className="live-feed-heading mini-label">Live Transport Victoria feeds</div>{(['vehiclePositions', 'tripUpdates', 'serviceAlerts'] as const).map(key => <FeedRow key={`live-${key}`} name={{ vehiclePositions: 'Live vehicle positions', tripUpdates: 'Live trip updates', serviceAlerts: 'Live service alerts' }[key]} feed={transport?.liveFeeds?.[key]} connected={connected} />)}</>}<div className="data-version"><strong>Static geometry</strong><span>Official GTFS · {site?.gtfsDatasetVersion ?? 'Loading dataset'}</span><span>{site?.gtfsStopIds?.length ?? 0} verified platforms · route {site?.routeShortName ?? '58'}</span></div><p className="small-note">All times use Melbourne local time. Feed age uses the source observation time.</p></div></details>
          </section>

          <section className="scenario-section" aria-labelledby="scenario-title">
            <div className="section-heading"><h3 id="scenario-title"><Icon name="route" />Simulation lab</h3><span className="lab-badge">Prototype</span></div>
            {!simulation ? <div className="normal-notice"><Icon name="info" /><p>Normal operation accepts physical sensor observations. No mock readings are used. Switch to Simulation mode to explore the prototype.</p></div> : <>
              <label className="field-label" htmlFor="scenario-select">Choose a scenario</label>
              <div className="select-wrap"><select id="scenario-select" value={selectedScenario} onChange={e => setSelectedScenario(e.target.value)} disabled={disabled}>{SCENARIOS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><Icon name="chevron" size={16} /></div>
              <p className="scenario-hint">{SCENARIOS.find(([id]) => id === selectedScenario)?.[2]}</p>
              <div className="playback-controls">
                <button className="primary-button" disabled={disabled} onClick={() => void command(`/scenarios/${selectedScenario}/start`)}><Icon name="play" size={14} strokeWidth={2} />Run scenario</button>
                <button className="square-button" disabled={disabled} aria-label={paused ? 'Resume scenario' : 'Pause scenario'} title={paused ? 'Resume' : 'Pause'} onClick={() => void command(paused ? '/scenarios/resume' : '/scenarios/pause')}><Icon name={paused ? 'play' : 'pause'} size={16} /></button>
                <button className="square-button" disabled={disabled} aria-label="Reset scenario" title="Reset scenario" onClick={() => void command('/scenarios/reset')}><Icon name="reset" size={16} /></button>
              </div>
              <div className="playback-status"><span className={`playback-dot ${paused ? 'paused' : ''}`} /><span>{snapshot?.scenario.manualLevel != null ? 'Manual control' : SCENARIOS.find(([id]) => id === snapshot?.scenario.id)?.[1] ?? 'Ready'} <span>· {paused ? 'Paused' : 'Running'}</span></span><span className="elapsed">{Math.floor(snapshot?.scenario.elapsedSeconds ?? 0)}s</span></div>
              <div className="manual-label"><label htmlFor="level-slider">Adjust water level</label><output htmlFor="level-slider">{Math.round(manual)}</output></div>
              <input id="level-slider" type="range" min="0" max="100" step="1" value={manual} disabled={!connected || !simulation} onChange={e => adjustManual(Number(e.target.value))} aria-label="Manual water scenario level" style={{ '--slider-fill': `${manual}%` } as CSSProperties} />
              <div className="range-captions"><span>0 / Low</span><span>100 / High</span></div>
              <div className="impact-label"><label htmlFor="transport-mode">Tram data source</label><div className="select-wrap inline"><select id="transport-mode" value={snapshot?.scenario.transportMode ?? 'auto'} disabled={disabled} onChange={e => void command('/settings', { transportMode: e.target.value })}><option value="auto">Live feed · mock fallback</option><option value="mock">Mock trams · demo only</option></select><Icon name="chevron" size={14} /></div></div>
              <RainControls snapshot={snapshot} disabled={disabled} command={command} />
              <div className="impact-label"><label htmlFor="impact-scope">Highlight impact</label><div className="select-wrap inline"><select id="impact-scope" value={status?.impactScope ?? 'local_segment'} disabled={disabled} onChange={e => void command('/settings', { impactScope: e.target.value })}><option value="local_segment">Local segment</option><option value="full_route_demo">Full route · demo only</option></select><Icon name="chevron" size={14} /></div></div>
            </>}
          </section>
          <p className="prototype-note"><Icon name="info" size={15} /><span>Decision-support research prototype.<br />Not an operational warning or flood prediction.</span></p>
        </div>
      </aside>
    </main>

    <footer className="event-footer">
      <div className="timeline-heading"><span className="mini-label">Recent activity</span><span><i className="live-dot" />Event timeline</span></div>
      <ol className="timeline-events">{timeline.length ? timeline.map((event, i) => <li className="timeline-event" key={event.id ?? i}><time>{formatTime(event.at ?? event.timestamp ?? event.createdAt)}</time><span>{event.hazardState ? <i className="event-dot" style={{ background: stateStyle(event.hazardState).color }} /> : <i className="event-dot neutral" />}{timelineMessage(event)}</span></li>) : <li className="timeline-empty">Platform transitions will appear here as observations arrive.</li>}</ol>
      <a href="/api/v1/events/export" download="southbank-evaluation.json" className="export-link" aria-label="Export evaluation events"><Icon name="download" size={16} /><span>Export events</span></a>
    </footer>
  </div>;
}

function timelineMessage(event: Snapshot['timeline'][number]) {
  if (event.type === 'state-transition' && event.hazardState) {
    const service = /service (\w+)/i.exec(event.message ?? '')?.[1];
    return `Hazard ${humanize(event.hazardState)}${service ? ` · Service ${humanize(service)}` : ''}`;
  }
  return event.message ?? humanize(event.type ?? 'Platform update');
}
function FeedRow({ name, feed, connected }: { name: string; feed?: Feed; connected: boolean }) {
  return <div className="feed-row"><div><strong>{name}</strong><span>Feed {formatTime(feed?.feedTimestamp)}</span><span>Fetched {formatTime(feed?.fetchedAt)}</span>{feed?.error && <span className="feed-error">{feed.error}</span>}</div><span className={`health-label ${connected ? feed?.freshness ?? 'unavailable' : 'stale'}`}>{connected ? feed?.freshness ?? 'unavailable' : 'stale'}</span></div>;
}
