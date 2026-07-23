// Relative, same-origin path: the frontend host proxies /api/* to the gateway
// and the httpOnly auth cookie only travels same-origin. Calling an absolute
// cross-origin host (nkz.robotika.cloud) drops the cookie -> 401.
const HYDRO_BASE = '/api/v1/hydrology';

// Auth is the httpOnly cookie (credentials: 'include'); the host intentionally
// omits the token from window.__nekazariAuthContext. We only add X-Tenant-ID
// and a mobile-WebView Bearer fallback, mirroring the other modules.
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const ctx = typeof window !== 'undefined' ? (window as any).__nekazariAuthContext : undefined;
  const tenantId = ctx?.tenantId || ctx?.getTenantId?.();
  const mobileToken = typeof window !== 'undefined' ? (window as any).__nekazariMobileToken : undefined;
  return {
    ...(extra || {}),
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
    ...(mobileToken ? { Authorization: `Bearer ${mobileToken}` } : {}),
  };
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${HYDRO_BASE}${path}`, { headers: authHeaders(), credentials: 'include' });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${HYDRO_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${HYDRO_BASE}${path}`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function del(path: string): Promise<void> {
  const resp = await fetch(`${HYDRO_BASE}${path}`, { method: 'DELETE', headers: authHeaders(), credentials: 'include' });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
}

export interface ZoneKpi {
  id: string;
  zoneId: string;
  twiMean: number;
  twiRange: string;
  areaHa: number;
  runoffMm?: number;
  peakFlowM3s?: number;
  sedimentYieldTonnes?: number;
  soilSaturationPct?: number;
  pondViability?: number;
  keylineGrade?: number;
  geometry?: GeoJSON.Geometry | null;
}

export type DataFidelity = 'ign_5m' | 'ign_25m' | 'degraded_flat' | 'unavailable' | string;

export interface ParcelSummaryKpis {
  twiMean?: number;
  twiMax?: number;
  slopeMean?: number;
  streamLengthM?: number;
  runoffMm?: number;
  peakFlowM3s?: number;
  sedimentYieldTonnes?: number;
  soilSaturationPct?: number;
  keylineGrade?: number;
  pondViability?: number;
  etoMm?: number;
  precipitationMm?: number;
  temperatureAvg?: number;
  temperatureMin?: number;
  soilMoisture?: number;
}

export interface ParcelSummary {
  status?: 'no_data' | string;
  observedAt?: string | null;
  dataFidelity?: DataFidelity | null;
  demSource?: string | null;
  soilSource?: string | null;
  vegetationSource?: string | null;
  kpis?: ParcelSummaryKpis;
}

export interface KeylineRequest {
  parcel_id: string;
  grade: number;
  spacing: number;
  lines: number;
}

export interface KeylineResponse {
  keypoint: { type: 'Point'; coordinates: number[] };
  keyline: { type: 'LineString'; coordinates: number[][] };
  parallel_lines: Array<{
    geometry: { type: 'LineString'; coordinates: number[][] };
    grade: number;
    direction: 'up' | 'down';
  }>;
  request: KeylineRequest;
  status: string;
}

export interface PondScoreRequest {
  parcel_id: string;
  center: number[];
  radius: number;
  depth: number;
}

export interface PondScoreResponse {
  pondScore: number;
  isViable: boolean;
  factors: Record<string, number>;
  request: PondScoreRequest;
  status: string;
}

export interface SwaleSuggestRequest {
  parcel_id: string;
  bank_height: number;
  trench_depth: number;
  trench_width: number;
}

export interface CheckDamSuggestRequest {
  parcel_id: string;
  height: number;
  width: number;
}

export interface AnalyzeResponse {
  job_id: string;
  status: string;
  [key: string]: unknown;
}

export interface JobStatus {
  job_id: string;
  status: 'queued' | 'started' | 'finished' | 'failed' | string;
  [key: string]: unknown;
}

export interface DesignSaveRequest {
  parcel_id: string;
  design_type: 'keyline' | 'pond' | 'swale' | 'check_dam';
  geometry: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  label?: string;
}

/** NGSI-LD normalized design entity as returned by list_designs (attrs are {type, value}). */
export interface DesignEntity {
  id: string;
  type: string;
  location?: { value?: GeoJSON.Geometry };
  'nkz:designType'?: { value?: string };
  'nkz:label'?: { value?: string };
  'nkz:parameters'?: { value?: Record<string, unknown> };
}

/** Gateway-safe export envelope for gpx/kml (see backend export_design). */
export interface ExportEnvelope {
  filename: string;
  mediaType: string;
  content: string;
}

export interface TwiOverlayResponse {
  url: string | null;
  bounds: { west: number; south: number; east: number; north: number } | null;
  status: 'ok' | 'not_generated' | string;
}

export const api = {
  // DEM analysis (async job)
  analyzeParcel: (parcelId: string) =>
    post<AnalyzeResponse>(`/analyze/${encodeURIComponent(parcelId)}`, {}),
  getJob: (jobId: string) => get<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`),

  // Zones
  getZones: (parcelId: string) => get<ZoneKpi[]>(`/parcels/${encodeURIComponent(parcelId)}/zones`),

  // Parcel summary (latest AgriParcelRecord surfaced as flat KPIs)
  getSummary: (parcelId: string) =>
    get<ParcelSummary>(`/parcels/${encodeURIComponent(parcelId)}/summary`),

  // Visualization overlays (JSON through the same-origin gateway)
  getTwiOverlay: (parcelId: string) =>
    get<TwiOverlayResponse>(`/visualization/${encodeURIComponent(parcelId)}/overlay/twi`),
  getFlows: (parcelId: string) =>
    get<GeoJSON.FeatureCollection>(`/visualization/${encodeURIComponent(parcelId)}/flows`),

  // Design generation
  generateKeyline: (req: KeylineRequest) => post<KeylineResponse>('/design/keyline/generate', req),
  scorePond: (req: PondScoreRequest) => post<PondScoreResponse>('/design/pond/score', req),
  suggestSwales: (req: SwaleSuggestRequest) => post('/design/swale/suggest', req),
  suggestCheckDams: (req: CheckDamSuggestRequest) => post('/design/check-dam/suggest', req),

  // Design CRUD
  listDesigns: (parcelId: string) =>
    get<DesignEntity[]>(`/design?parcel_id=${encodeURIComponent(parcelId)}`),
  saveDesign: (req: DesignSaveRequest) => post<{ id: string; status: string }>('/design', req),
  updateDesign: (id: string, req: DesignSaveRequest) => put(`/design/${encodeURIComponent(id)}`, req),
  deleteDesign: (id: string) => del(`/design/${encodeURIComponent(id)}`),

  // Export — gpx/kml come back as a JSON envelope (gateway 502s non-JSON bodies);
  // geojson returns a GeoJSON Feature. Callers build the Blob client-side.
  exportDesign: (designId: string, format: 'gpx' | 'kml' | 'geojson') =>
    get<ExportEnvelope | GeoJSON.Feature>(
      `/design/${encodeURIComponent(designId)}/export?format=${format}`,
    ),
};
