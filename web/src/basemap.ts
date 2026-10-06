import type { Position } from './types';

export type Bounds = { north: number; south: number; east: number; west: number };
export type MapSize = { width: number; height: number };
export type MapViewState = { x: number; y: number; zoom: number };
export type BasemapGeometry =
  | { type: 'Point'; coordinates: Position }
  | { type: 'LineString'; coordinates: Position[] }
  | { type: 'MultiLineString' | 'Polygon'; coordinates: Position[][] }
  | { type: 'MultiPolygon'; coordinates: Position[][][] };
export type BasemapFeature = {
  type: 'Feature'; geometry: BasemapGeometry;
  properties: { kind: string; osmId: string; name?: string; roadClass?: string; layer: number; bridge: boolean; tunnel: boolean; landmarkType?: string; waterType?: string; [key: string]: unknown };
};
export type BasemapData = {
  type: 'FeatureCollection'; features: BasemapFeature[];
  metadata: { bounds: Bounds; attribution: string; licenseUrl: string; sourceUrl: string; retrievedAt: string; osmBaseTimestamp: string };
};
// A display camera, independent of the verified GTFS stop and risk footprint.
export const CITY_BOUNDS: Bounds = { north: -37.8172, south: -37.8298, west: 144.9515, east: 144.969 };

export function createProjection(bounds: Bounds, size: MapSize) {
  const aspect = Math.cos((bounds.north + bounds.south) * Math.PI / 360);
  const mobile = size.width < 600;
  const top = mobile ? 96 : 122, bottom = mobile ? 90 : 165;
  const scale = Math.min((size.width - (mobile ? 28 : 80)) / ((bounds.east - bounds.west) * aspect), Math.max(180, size.height - top - bottom) / (bounds.north - bounds.south));
  const midLon = (bounds.east + bounds.west) / 2, midLat = (bounds.north + bounds.south) / 2;
  const project = ([lon, lat]: Position): Position => [size.width / 2 + (lon - midLon) * aspect * scale, (size.height + top - bottom) / 2 - (lat - midLat) * scale];
  return { project, pixelsPerMeter: scale / 111320 };
}
export type Projection = ReturnType<typeof createProjection>;
export function linePath(line: Position[], project: Projection['project'], closed = false) {
  return line.map((p, i) => `${i ? 'L' : 'M'}${project(p).map(n => n.toFixed(2)).join(',')}`).join(' ') + (closed ? ' Z' : '');
}
export function geometryLines(geometry: BasemapGeometry): Position[][] {
  switch (geometry.type) {
    case 'Point': return [[geometry.coordinates]];
    case 'LineString': return [geometry.coordinates];
    case 'Polygon': case 'MultiLineString': return geometry.coordinates;
    case 'MultiPolygon': return geometry.coordinates.flat();
  }
}
export function isArea(geometry: BasemapGeometry) { return geometry.type === 'Polygon' || geometry.type === 'MultiPolygon'; }
export function onScreen([x, y]: Position, view: MapViewState, size: MapSize): Position {
  return [size.width / 2 + view.x + (x - size.width / 2) * view.zoom, size.height / 2 + view.y + (y - size.height / 2) * view.zoom];
}
export function roadWidth(roadClass?: string) {
  return ({ motorway: 8, trunk: 8, primary: 7, secondary: 6, tertiary: 5, residential: 4, unclassified: 4, living_street: 3, service: 2.5, pedestrian: 2.4, footway: 1.1, path: 1.1, cycleway: 1.2, steps: .8 } as Record<string, number>)[roadClass ?? ''] ?? 1.5;
}
export type PreparedFeature = { feature: BasemapFeature; d: string; lines: Position[][]; box: [number, number, number, number]; area: boolean };
export function prepareBasemap(data: BasemapData, projection: Projection): PreparedFeature[] {
  return data.features.filter(f => !['corridor', 'platform', 'elevator'].includes(f.properties.roadClass ?? '') && !(f.properties.layer < 0 || f.properties.tunnel)).map(feature => {
    const lines = geometryLines(feature.geometry).map(line => line.map(projection.project));
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const line of lines) for (const [x, y] of line) { left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y); }
    const area = isArea(feature.geometry);
    return { feature, area, lines, box: [left, top, right, bottom], d: lines.map(line => linePath(line, p => p, area)).join(' ') };
  });
}

export type MapLabel = { id: string; name: string; x: number; y: number; angle: number; kind: string; priority: number; width: number; height: number };
// Names remain source data. This list only chooses which real landmarks get
// priority at neighbourhood scale; it never supplies their coordinates.
const prominent = /^(Crown Melbourne|Melbourne (Convention|Exhibition) Centre|Flinders Street(?: Railway Station)?|Southern Cross(?: Station)?|Eureka Tower|South Melbourne Market|SEA LIFE Melbourne Aquarium|Federation Square)$/i;
export function placeLabels(items: PreparedFeature[], view: MapViewState, size: MapSize, reserved: [number, number, number, number][], coverage?: [number, number, number, number]): MapLabel[] {
  const candidates: MapLabel[] = [];
  for (const item of items) {
    const p = item.feature.properties, name = p.name;
    if (!name) continue;
    let point: Position, angle = 0, priority = 0, kind = p.kind, displayName = name;
    if (item.feature.geometry.type === 'Point') {
      if (kind !== 'landmark') continue;
      priority = prominent.test(name) ? 100 : p.landmarkType === 'place' ? 95 : 35;
      if (priority < 95 && view.zoom < 1.8) continue;
      point = item.lines[0][0];
    } else if (kind === 'water' && p.waterType === 'river' && !item.area) {
      const line = item.lines[0]; point = line[Math.floor(line.length / 2)]; priority = 120;
    } else if ((kind === 'road' || kind === 'bridge') && !item.area) {
      if (roadWidth(p.roadClass) < 3 && view.zoom < 2) continue;
      displayName = name.replace(/\bStreet\b/g, 'St').replace(/\bRoad\b/g, 'Rd');
      // OSM ways contain dense intermediate vertices even on straight streets.
      // Find a nearly straight span of the source line, rather than requiring
      // a single pair of vertices to be long enough for a label.
      let longest = 0; point = item.lines[0][0];
      for (const line of item.lines) for (let i = 0; i < line.length - 1; i++) {
        for (let j = i + 1; j < Math.min(line.length, i + 32); j++) {
          const [a, b] = [line[i], line[j]], dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy);
          if (length <= longest) continue;
          if (line.slice(i + 1, j).some(q => Math.abs(dy * (q[0] - a[0]) - dx * (q[1] - a[1])) / length > 3 / view.zoom)) break;
          longest = length; point = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; angle = Math.atan2(dy, dx) * 180 / Math.PI;
        }
      }
      if (longest * view.zoom < displayName.length * 5.4 + 8) continue;
      if (angle > 90) angle -= 180; if (angle < -90) angle += 180;
      priority = kind === 'bridge' ? 85 : 45 + roadWidth(p.roadClass);
    } else if (kind === 'bridge' && item.area) {
      point = [(item.box[0] + item.box[2]) / 2, (item.box[1] + item.box[3]) / 2]; priority = 90;
    } else if (kind === 'park' && view.zoom >= 1.5 && (item.box[2] - item.box[0]) * view.zoom > 75) {
      point = [(item.box[0] + item.box[2]) / 2, (item.box[1] + item.box[3]) / 2]; priority = 40;
    } else continue;
    if (coverage && (point[0] < coverage[0] || point[0] > coverage[2] || point[1] < coverage[1] || point[1] > coverage[3])) continue;
    const [x, y] = onScreen(point, view, size);
    const textWidth = displayName.length * (priority >= 100 ? 6.4 : 5.8) + 16;
    const radians = angle * Math.PI / 180;
    const width = Math.abs(textWidth * Math.cos(radians)) + Math.abs(16 * Math.sin(radians));
    const height = Math.abs(textWidth * Math.sin(radians)) + Math.abs(16 * Math.cos(radians));
    if (x - width / 2 < 8 || x + width / 2 > size.width - 8 || y - height / 2 < 12 || y + height / 2 > size.height - 32) continue;
    candidates.push({ id: `${p.osmId}-${kind}`, name: displayName, x, y, angle, priority, kind, width, height });
  }
  const occupied = [...reserved], names = new Set<string>(), placed: MapLabel[] = [];
  for (const label of candidates.sort((a, b) => b.priority - a.priority)) {
    if (names.has(label.name)) continue;
    const box: [number, number, number, number] = [label.x - label.width / 2 - 4, label.y - label.height / 2 - 4, label.x + label.width / 2 + 4, label.y + label.height / 2 + 4];
    if (occupied.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
    occupied.push(box); names.add(label.name); placed.push(label);
  }
  return placed;
}
