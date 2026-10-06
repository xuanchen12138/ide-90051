import { memo, useMemo } from 'react';
import { onScreen, roadWidth } from './basemap';
import type { BasemapData, MapSize, MapViewState, PreparedFeature, Projection } from './basemap';

type Props = { data: BasemapData; items: PreparedFeature[]; projection: Projection; view: MapViewState; size: MapSize };
const order: Record<string, number> = { park: 0, water: 1, building: 2, road: 3, rail: 4, bridge: 5 };
// Visual tiers for the architectural-model palette: corridors darken with importance.
const TIER_RANK: Record<string, number> = { minor: 0, local: 1, collector: 2, major: 3 };
function tierRank(roadClass?: string) { return TIER_RANK[roadTier(roadClass)]; }
function roadTier(roadClass?: string) {
  if (['motorway', 'trunk', 'primary'].includes(roadClass ?? '')) return 'major';
  if (['secondary', 'tertiary'].includes(roadClass ?? '')) return 'collector';
  if (['residential', 'unclassified', 'living_street'].includes(roadClass ?? '')) return 'local';
  return 'minor';
}

// Sensor SSE updates don't rebuild the static city geometry. Only camera moves
// change this viewport-culling pass; polygon holes use the even-odd fill rule.
export default memo(function BasemapLayer({ data, items, projection, view, size }: Props) {
  const visible = useMemo(() => items.filter(({ feature, box }) => {
    if (feature.geometry.type === 'Point') return false;
    const a = onScreen([box[0], box[1]], view, size), b = onScreen([box[2], box[3]], view, size);
    return b[0] >= -80 && a[0] <= size.width + 80 && b[1] >= -80 && a[1] <= size.height + 80;
  }).sort((a, b) => (order[a.feature.properties.kind] ?? 6) - (order[b.feature.properties.kind] ?? 6) || a.feature.properties.layer - b.feature.properties.layer || tierRank(a.feature.properties.roadClass) - tierRank(b.feature.properties.roadClass)), [items, size, view]);
  const bounds = data.metadata.bounds;
  const [left, top] = projection.project([bounds.west, bounds.north]);
  const [right, bottom] = projection.project([bounds.east, bounds.south]);
  return <g className="city-basemap" data-testid="city-basemap">
    <defs><clipPath id="city-coverage"><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
    <rect className="basemap-coverage" x={left} y={top} width={right - left} height={bottom - top} />
    <g clipPath="url(#city-coverage)">
      {renderFeatures(visible.filter(({ feature }) => (order[feature.properties.kind] ?? 6) < order.building), view)}
      <g className="building-layer">{renderFeatures(visible.filter(({ feature }) => feature.properties.kind === 'building'), view)}</g>
      {renderFeatures(visible.filter(({ feature }) => (order[feature.properties.kind] ?? 6) > order.building), view)}
    </g>
  </g>;
});

function renderFeatures(items: PreparedFeature[], view: MapViewState) {
  return items.map(({ feature, d, area }) => {
    const p = feature.properties, kind = p.kind;
    if (kind === 'water' && !area) return null; // Name-bearing river centreline is a label source, not a bank.
    const road = (kind === 'road' || kind === 'bridge') && !area;
    const minor = road && roadWidth(p.roadClass) < 3;
    const width = roadWidth(p.roadClass);
    if (minor && view.zoom < (p.roadClass === 'service' || kind === 'bridge' ? .75 : 1.35)) return null;
    const key = `${p.osmId}-${kind}`;
    return <g key={key} className={`basemap-feature ${kind} ${area ? 'area' : 'line'} ${minor ? 'minor' : ''}`} data-road={road ? roadTier(p.roadClass) : undefined}>
      {road && !minor && <path className="road-casing" d={d} strokeWidth={width + (kind === 'bridge' ? 3 : 1.5)} />}
      <path data-map-kind={kind} data-osm-id={p.osmId} d={d} fillRule="evenodd" {...(road ? { strokeWidth: width } : {})}><title>{p.name ?? `${kind} · ${p.osmId}`}</title></path>
    </g>;
  });
}
