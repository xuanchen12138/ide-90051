import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { usePlatform } from './api';
import { delayLabel, formatAge, formatTime, SCENARIOS, STATES, stateStyle } from './presentation';
import type { Feed, HazardState, Snapshot } from './types';
import Icon from './Icon';
import MapView from './MapView';

export default function App() {
  const { site, geometry, basemap, basemapFailed, snapshot, connected, busy, error, now, command, clearError } = usePlatform();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState('water-rising');
  const [manual, setManual] = useState(0);
  const manualActive = useRef(false);
  const manualTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const status = snapshot?.status;
  const state: HazardState = connected ? status?.hazardState ?? 'UNKNOWN' : 'UNKNOWN';
  const appearance = stateStyle(state);
  const simulation = snapshot?.scenario.mode !== 'normal';
  const sensor = snapshot?.sensor;
  const disabled = busy || !connected;
  useEffect(() => {
    if (!manualActive.current) setManual(snapshot?.sensor?.scenarioLevel ?? 0);
  }, [snapshot?.sensor?.scenarioLevel]);
  useEffect(() => () => { if (manualTimer.current) clearTimeout(manualTimer.current); }, []);
  const adjustManual = (value: number) => {
    setManual(value); manualActive.current = true;
    if (manualTimer.current) clearTimeout(manualTimer.current);
    manualTimer.current = setTimeout(() => {
      void command('/scenarios/manual', { level: value }).finally(() => { manualActive.current = false; });
    }, 300);
  };
  const sourceName = sensor?.source === 'mock' ? 'Simulated sensor' : sensor?.source === 'physical' ? 'Physical sensor' : 'No sensor';
  const timeline = [...(snapshot?.timeline ?? [])].reverse().slice(0, 3);
  const freshVehicles = connected ? snapshot?.transport.vehicles.filter(v => v.freshness === 'fresh') ?? [] : [];
  const freshTrips = connected ? snapshot?.transport.tripUpdates.filter(t => t.freshness === 'fresh') ?? [] : [];
  const latestTrip = freshTrips[0];
  return <div className={`app ${sheetOpen ? 'sheet-open' : ''}`} style={{ '--risk': appearance.color, '--risk-ink': appearance.ink } as CSSProperties}>
    <a href="#status-panel" className="skip-link">Skip to current status</a>
    <header className="app-header">
      <a href="/" className="brand" aria-label="Southbank Flood watch home"><span className="brand-mark"><Icon name="water" size={23} /></span><span>Southbank<span className="brand-sub">Flood watch</span></span></a>
      <span className="header-divider" /><div className="header-context"><span>LOCAL EARLY WARNING</span><strong>Melbourne, Victoria</strong></div>
      <div className="header-right"><span className={`connection ${connected ? 'connected' : ''}`} title={connected ? 'Receiving platform updates' : 'Reconnecting; any retained data is an old snapshot'}><i />{connected ? 'Connected' : snapshot ? 'Disconnected' : 'Connecting'}</span>
        <div className="mode-switch" role="group" aria-label="Operating mode"><button aria-pressed={!simulation} disabled={disabled} onClick={() => void command('/settings', { mode: 'normal' })}>Normal operation</button><button aria-pressed={simulation} disabled={disabled} onClick={() => void command('/settings', { mode: 'simulation' })}><span className="tiny-diamond" />Simulation mode</button></div>
      </div>
    </header>

    <main className="workspace">
      <section className="map-stage" aria-label="Site map">
        <div className="map-heading"><div className="eyebrow"><span className="route-badge">58</span> LOCAL FLOOD MONITORING</div><h1>Southbank, Melbourne</h1><p>City Rd / Kings Way <span>—</span> Stop 116</p></div>
        {site && geometry ? <MapView site={site} geometry={geometry} basemap={basemap} basemapFailed={basemapFailed} snapshot={snapshot} connected={connected} /> : <div className="map-loading"><span className="loading-ring" /><strong>Locating the tram corridor</strong><span>Loading verified Transport Victoria geometry</span></div>}
        {!connected && snapshot && <div className="disconnect-banner" role="alert"><Icon name="info" /><span><strong>Connection lost.</strong> Last snapshot {formatTime(status?.evaluatedAt)} AEST/AEDT. Reconnecting…</span></div>}
        <div className="map-legend"><span className="legend-title">HAZARD STATE</span><div className="legend-states">{Object.entries(STATES).map(([key, value]) => <span key={key} className={state === key ? 'legend-item active' : 'legend-item'}><i style={{ background: value.color }} className={key === 'UNKNOWN' ? 'dashed' : ''} />{value.label}</span>)}</div><span className="water-legend"><i />Conceptual flood extent <span className="legend-note">· illustrative only</span></span></div>
      </section>

      <aside className="status-panel" id="status-panel" aria-label="Stop status and scenario controls">
        <button className="sheet-toggle" onClick={() => setSheetOpen(v => !v)} aria-expanded={sheetOpen} aria-controls="panel-body"><span className="sheet-handle" /><span>{sheetOpen ? 'Hide details' : 'View details & controls'}</span><Icon name="chevron" /></button>
        <div className="status-overview">
          <div className="section-topline"><span className="eyebrow">LOCAL WATER RISK</span><span className={`source-pill ${simulation ? 'simulation' : ''}`}>{simulation ? 'SIMULATED' : 'OBSERVATION'}</span></div>
          <div className="hazard-headline" aria-live="polite" aria-atomic="true"><h2 data-testid="hazard-state">{appearance.label}</h2><span className="hazard-symbol" aria-hidden="true">{appearance.symbol}</span></div>
          <p className="hazard-summary">{!connected ? snapshot ? 'Live updates interrupted. The current risk is unknown.' : 'Waiting for the first platform observation.' : simulation ? appearance.summary : appearance.summary.replace('simulated ', '')}</p>
          <div className="always-visible-sources"><span><i className={`freshness-dot ${connected ? status?.dataFreshness.sensor ?? 'unavailable' : 'stale'}`} />{sourceName}</span><time dateTime={status?.evaluatedAt} title={status?.evaluatedAt}>Updated {formatTime(status?.evaluatedAt)}<span className="time-zone"> Melbourne</span></time></div>
          <div className="mobile-service-summary"><span>Tram: {humanize(connected ? status?.serviceState ?? 'UNKNOWN' : 'UNKNOWN')}</span><span>{snapshot?.transport.source === 'fixture' ? 'Synthetic fixture' : 'Transport Victoria'} · {connected ? status?.dataFreshness.transport ?? 'unavailable' : 'stale'}</span></div>
        </div>

        <div className="panel-body" id="panel-body">
          {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={clearError} aria-label="Dismiss error"><Icon name="close" size={16} /></button></div>}
          {simulation && <div className="simulation-notice"><span className="tiny-diamond" /><span>Simulated impact — not an official service status.</span></div>}
          <section className="sensor-section" aria-labelledby="sensor-title">
            <div className="measurement"><div><h3 id="sensor-title">Water scenario level</h3><div className="level-reading"><strong data-testid="scenario-level">{connected && sensor?.scenarioLevel != null ? Math.round(sensor.scenarioLevel) : '—'}</strong><span>/ 100</span></div></div><div className="trend"><Icon name={sensor?.trend === 'rising' ? 'arrow' : sensor?.trend === 'falling' ? 'arrow' : 'water'} /><span>{sensor?.trend === 'rising' ? 'Rising' : sensor?.trend === 'falling' ? 'Receding' : sensor?.trend === 'steady' ? 'Steady' : 'Unknown trend'}</span></div></div>
            <p className="small-note">Unitless demonstration scale · not measured depth</p>
            <div className="reason-block"><span className="mini-label">WHY THIS STATE</span><p>{!connected ? 'Current risk cannot be confirmed because platform updates are interrupted. Any retained observations below belong to the last received snapshot.' : status?.reasons?.length ? status.reasons.join(' ') : 'The platform needs a valid, recent water observation to evaluate this location.'}</p>{connected && status?.recommendedAction && <p className="recommended-action">{status.recommendedAction}</p>}</div>
          </section>

          <section className="transport-section" aria-labelledby="transport-title">
            <div className="section-heading"><h3 id="transport-title"><Icon name="tram" />Tram service</h3><span className="service-state" data-testid="service-state">{humanize(connected ? status?.serviceState ?? 'UNKNOWN' : 'UNKNOWN')}</span></div>
            <div className="source-line"><span>{snapshot?.transport.source === 'fixture' ? 'SYNTHETIC TRANSPORT FIXTURE' : 'TRANSPORT VICTORIA · OBSERVED'}</span><span className={`health-label ${connected ? status?.dataFreshness.transport : 'stale'}`}>{connected ? status?.dataFreshness.transport ?? 'unavailable' : snapshot ? 'stale' : 'unavailable'}</span></div>
            {snapshot?.transport.alerts?.length ? <div className="alerts">{snapshot.transport.alerts.slice(0, 3).map((alert, i) => <article className="service-alert" key={alert.id ?? i}><span className="alert-provenance">{!connected && 'LAST RECEIVED · '}{alert.source === 'fixture' || snapshot.transport.source === 'fixture' ? 'SYNTHETIC ALERT · TEST ONLY' : 'OFFICIAL SERVICE ALERT'}</span><strong>{alert.header}</strong>{alert.description && <p>{alert.description}</p>}<time>{alert.activeFrom ? `From ${formatTime(alert.activeFrom)}` : `Feed ${formatTime(snapshot.transport.feeds?.serviceAlerts?.feedTimestamp)}`}</time></article>)}</div> : <p className="transport-summary">{connected && snapshot?.transport.feeds?.serviceAlerts?.freshness === 'fresh' ? 'No relevant service alert in the current feed.' : 'Current service conditions cannot be confirmed.'}</p>}
            <div className="transport-stats"><span><strong>{connected ? freshVehicles.length : '—'}</strong> fresh tram positions</span><span><strong>{connected ? freshTrips.length : '—'}</strong> fresh trip updates</span></div>
            {latestTrip ? <p className="small-note">Latest trip: {latestTrip.scheduleRelationship === 'CANCELED' ? 'Canceled in the transport feed' : latestTrip.stopScheduleRelationship === 'SKIPPED' ? 'This stop is skipped' : latestTrip.stopScheduleRelationship === 'NO_DATA' ? 'No stop prediction available' : delayLabel(latestTrip.arrivalDelaySeconds ?? latestTrip.departureDelaySeconds ?? latestTrip.tripDelaySeconds)}. Cause is unconfirmed.</p> : null}
            <details className="data-details"><summary>Data sources & timestamps <Icon name="chevron" size={14} /></summary><div className="feed-list"><div className="feed-row"><div><strong>{sourceName}</strong><span>Observed {formatTime(sensor?.observedAt)} · {formatAge(sensor?.observedAt, now)}</span><span>Received {formatTime(sensor?.receivedAt)} · quality {sensor?.quality ?? 'unknown'}</span></div><span className={`health-label ${connected ? status?.dataFreshness.sensor : 'stale'}`}>{connected ? status?.dataFreshness.sensor ?? 'unavailable' : 'stale'}</span></div>{(['vehiclePositions', 'tripUpdates', 'serviceAlerts'] as const).map(key => <FeedRow key={key} name={{ vehiclePositions: 'Vehicle positions', tripUpdates: 'Trip updates', serviceAlerts: 'Service alerts' }[key]} feed={snapshot?.transport.feeds?.[key]} connected={connected} />)}<div className="data-version"><strong>Static geometry</strong><span>Official GTFS · {site?.gtfsDatasetVersion ?? 'Loading dataset'}</span><span>{site?.gtfsStopIds?.length ?? 0} verified platforms · route {site?.routeShortName ?? '58'}</span></div><p className="small-note">All times use Melbourne local time. Feed age uses the source observation time.</p></div></details>
          </section>

          <section className="scenario-section" aria-labelledby="scenario-title">
            <div className="section-heading"><h3 id="scenario-title">Simulation lab</h3><span className="lab-badge">PROTOTYPE</span></div>
            {!simulation ? <div className="normal-notice"><Icon name="info" /><p>Normal operation accepts physical sensor observations. No mock readings are used. Switch to Simulation mode to explore the prototype.</p></div> : <>
              <label className="field-label" htmlFor="scenario-select">Choose a scenario</label><div className="select-wrap"><select id="scenario-select" value={selectedScenario} onChange={e => setSelectedScenario(e.target.value)} disabled={disabled}>{SCENARIOS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><Icon name="chevron" size={16} /></div>
              <div className="playback-controls"><button className="primary-button" disabled={disabled} onClick={() => void command(`/scenarios/${selectedScenario}/start`)}><Icon name="play" size={16} />Run scenario</button><button className="square-button" disabled={disabled} aria-label={snapshot?.scenario.paused ? 'Resume scenario' : 'Pause scenario'} title={snapshot?.scenario.paused ? 'Resume' : 'Pause'} onClick={() => void command(snapshot?.scenario.paused ? '/scenarios/resume' : '/scenarios/pause')}><Icon name={snapshot?.scenario.paused ? 'play' : 'pause'} size={17} /></button><button className="square-button" disabled={disabled} aria-label="Reset scenario" title="Reset scenario" onClick={() => void command('/scenarios/reset')}><Icon name="reset" size={17} /></button></div>
              <div className="playback-status"><span className={`playback-dot ${snapshot?.scenario.paused ? 'paused' : ''}`} /><span>{snapshot?.scenario.manualLevel != null ? 'Manual control' : SCENARIOS.find(([id]) => id === snapshot?.scenario.id)?.[1] ?? 'Ready'} <span>· {snapshot?.scenario.paused ? 'Paused' : 'Running'}</span></span><span className="elapsed">{Math.floor(snapshot?.scenario.elapsedSeconds ?? 0)}s</span></div>
              <div className="manual-label"><label htmlFor="level-slider">Adjust water level</label><output htmlFor="level-slider">{Math.round(manual)}</output></div><input id="level-slider" type="range" min="0" max="100" step="1" value={manual} disabled={!connected || !simulation} onChange={e => adjustManual(Number(e.target.value))} aria-label="Manual water scenario level" style={{ '--slider-fill': `${manual}%` } as CSSProperties} /><div className="range-captions"><span>0 / Low</span><span>100 / High</span></div>
              <div className="impact-label"><label htmlFor="impact-scope">Highlight impact</label><select id="impact-scope" value={status?.impactScope ?? 'local_segment'} disabled={disabled} onChange={e => void command('/settings', { impactScope: e.target.value })}><option value="local_segment">Local segment</option><option value="full_route_demo">Full route · demo only</option></select></div>
            </>}
          </section>
          <p className="prototype-note"><Icon name="info" size={15} /><span>Decision-support research prototype.<br />Not an operational warning or flood prediction.</span></p>
        </div>
      </aside>
    </main>
    <footer className="event-footer"><div className="timeline-heading"><span className="mini-label">RECENT ACTIVITY</span><span><i className="live-dot" />Event timeline</span></div><div className="timeline-events">{timeline.length ? timeline.map((event, i) => <div className="timeline-event" key={event.id ?? i}><time>{formatTime(event.at ?? event.timestamp ?? event.createdAt)}</time><span>{event.message ?? timelineMessage(event)}</span></div>) : <div className="timeline-empty">Platform transitions will appear here as observations arrive.</div>}</div><a href="/api/v1/events/export" download="southbank-evaluation.json" className="export-link" aria-label="Export evaluation events"><Icon name="download" size={17} /><span>Export events</span></a></footer>
  </div>;
}

function humanize(value: string) { return value.charAt(0) + value.slice(1).toLowerCase().replaceAll('_', ' '); }
function timelineMessage(event: Snapshot['timeline'][number]) { return event.hazardState ? `Hazard state → ${humanize(event.hazardState)}` : humanize(event.type ?? 'Platform update'); }
function FeedRow({ name, feed, connected }: { name: string; feed?: Feed; connected: boolean }) {
  return <div className="feed-row"><div><strong>{name}</strong><span>Feed {formatTime(feed?.feedTimestamp)}</span><span>Fetched {formatTime(feed?.fetchedAt)}</span>{feed?.error && <span className="feed-error">{feed.error}</span>}</div><span className={`health-label ${connected ? feed?.freshness ?? 'unavailable' : 'stale'}`}>{connected ? feed?.freshness ?? 'unavailable' : 'stale'}</span></div>;
}

