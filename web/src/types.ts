export type HazardState = 'NORMAL' | 'WATCH' | 'WARNING' | 'CRITICAL' | 'UNKNOWN';
export type Freshness = 'fresh' | 'stale' | 'unavailable';
export type ImpactScope = 'local_segment' | 'full_route_demo';
export type Position = [number, number];
export type Geometry = { type: 'LineString' | 'MultiLineString' | 'Point' | 'Polygon'; coordinates: Position | Position[] | Position[][] };
export type Feature = { type: 'Feature'; properties: Record<string, unknown> & { kind: string }; geometry: Geometry };
export type GeoJSON = { type: 'FeatureCollection'; features: Feature[] };
export type Site = {
  siteId: string; displayName: string; passengerStopNumber: string; routeShortName: string;
  gtfsRouteIds: string[]; gtfsStopIds: string[]; gtfsShapeIds: string[]; gtfsDatasetVersion: string;
  center: { latitude: number; longitude: number };
  focusBounds: { north: number; south: number; east: number; west: number };
  conceptualFlood: { type: 'Polygon'; coordinates: Position[][] };
  stops: { stopId: string; name: string; latitude: number; longitude: number; directions: { directionId: string; headsigns: string[]; tripCount: number }[] }[];
  geometryUrl: string;
};
export type Sensor = {
  readingId: string; sensorId: string; observedAt: string; receivedAt: string;
  scenarioLevel: number | null; trend: string; quality: string; source: string;
  floatLevel?: -1 | 0 | 1 | 2 | null; lowerFloat?: boolean | null; upperFloat?: boolean | null; sensorUptimeMs?: number | null;
};
export type Weather = { intensityMmPerHour: number | null; source: 'mock' | 'physical' | 'unavailable'; observedAt: string | null; freshness: Freshness };
export type Feed = { source?: string; freshness: Freshness; feedTimestamp?: string | null; fetchedAt?: string | null; error?: string | null };
export type Alert = { id?: string; header: string; description?: string; effect?: string; source?: string; activeFrom?: string; activeUntil?: string };
export type Snapshot = {
  status: {
    hazardState: HazardState; serviceState: string; displayState: HazardState;
    impactScope: ImpactScope; simulated: boolean; reasons: string[]; reasonCodes?: string[];
    recommendedAction?: string; evaluatedAt: string; serviceSource?: string;
    dataFreshness: { sensor: Freshness; transport: Freshness };
  };
  sensor: Sensor | null;
  weather?: Weather;
  transport: {
    source: string; freshness: Freshness; fetchedAt?: string; feedTimestamp?: string;
    fallback?: boolean; fallbackReason?: string; liveFeeds?: { vehiclePositions: Feed; tripUpdates: Feed; serviceAlerts: Feed };
    feeds: { vehiclePositions: Feed; tripUpdates: Feed; serviceAlerts: Feed };
    vehicles: { source?: string; vehicleId?: string; tripId?: string; latitude: number; longitude: number; bearing?: number; observedAt?: string; freshness?: Freshness }[];
    tripUpdates: { source?: string; tripId?: string; stopId?: string; arrivalDelaySeconds?: number; departureDelaySeconds?: number; tripDelaySeconds?: number; freshness?: Freshness; stopScheduleRelationship?: string; scheduleRelationship?: string }[];
    alerts: Alert[];
  };
  scenario: { id: string; paused: boolean; elapsedSeconds: number; manualLevel: number | null; mode: 'simulation' | 'normal'; transportMode?: 'auto' | 'mock'; impactScope: ImpactScope };
  timeline: { id?: string | number; type?: string; message?: string; timestamp?: string; at?: string; createdAt?: string; hazardState?: HazardState }[];
  serverTime: string;
};
