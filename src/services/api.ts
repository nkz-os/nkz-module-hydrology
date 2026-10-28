// The session cookie is host-only on the API host, so calls go to the API origin
// the host page injects at runtime; a relative path would hit the frontend host,
// where the cookie never travels (401).
export const API_ORIGIN = (
  (typeof window !== 'undefined' ? window.__ENV__?.VITE_API_URL : undefined) ?? ''
).replace(/\/$/, '');
const HYDRO_BASE = `${API_ORIGIN}/api/v1/hydrology`;

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

/** HTTP failure carrying the status, so callers can tell 403 from 422. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number) {
    super(`HTTP ${status}`);
    this.status = status;
  }
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
  if (!resp.ok) throw new ApiError(resp.status);
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

export type CalculationMode = 'storm' | 'retention';
export type ReturnPeriod = 10 | 25 | 100;

export interface ParcelSettings {
  mode: CalculationMode;
  return_period_years: ReturnPeriod;
  is_default: boolean;
  updated_by?: string | null;
  updated_at?: string | null;
}

/** Design rain behind the numbers of the latest record (absent on legacy records). */
export interface DesignInfo {
  calculationMode?: CalculationMode;
  returnPeriodYears?: number;
  designRainMm?: number;
  designRainCiLowMm?: number;
  designRainCiHighMm?: number;
  designRainLowConfidence?: boolean;
  designRainSource?: string;
  designRainStatus?: 'ok' | 'not_available' | string;
  designRainReason?: string;
}

export interface ParcelSummary {
  status?: 'no_data' | string;
  observedAt?: string | null;
  dataFidelity?: DataFidelity | null;
  demSource?: string | null;
  soilSource?: string | null;
  vegetationSource?: string | null;
  kpis?: ParcelSummaryKpis;
  design?: DesignInfo;
}

export interface KeylineRequest {
  parcel_id: string;
  grade: number;
  spacing: number;
  /** Rows of lines seeded out from the keylines; omitted or null = as far as the terrain allows. */
  lines?: number | null;
  /** Traced lines shorter than this (m) are dropped; default 100. */
  min_line_m?: number;
}

export type KeylineStatus = 'ok' | 'no_data' | 'no_keypoint' | 'terrain_too_coarse';

export interface KeylineLineGrade {
  grade: number;
  max_grade_20m: number;
}

export interface KeylineResponse {
  status: KeylineStatus;
  keypoint: { type: 'Point'; coordinates: number[] } | null;
  keyline: { type: 'LineString'; coordinates: number[][] } | null;
  keypoints?: Array<{ type: 'Point'; coordinates: number[] }>;
  keylines?: Array<{ type: 'LineString'; coordinates: number[][] }>;
  /** Measured grade of `keyline` and of each entry of `keylines` (same order). */
  keyline_metrics?: KeylineLineGrade | null;
  keylines_metrics?: KeylineLineGrade[];
  parallel_lines?: Array<{
    geometry: { type: 'LineString'; coordinates: number[][] };
    /** Measured mean fall along the line (fraction, 0.005 = 0.5 %). */
    grade: number;
    /** Largest fall over any 20 m of the line; never above max_line_grade. */
    max_grade_20m?: number;
    /** 'line': traced on the terrain at the design grade, about one spacing from its neighbours. */
    direction: 'line';
  }>;
  /** Cap on max_grade_20m of every line (fraction). */
  max_line_grade?: number;
  /** True when the layout stopped at its seed limit with ground left uncovered. */
  coverage_truncated?: boolean;
  /** Share of the parcel within half a spacing of a line (%). */
  coverage_pct?: number;
  request?: KeylineRequest;
  /** Present when status is terrain_too_coarse. */
  cell_size_m?: number;
  max_cell_size_m?: number;
}

export interface PondScoreRequest {
  parcel_id: string;
  center: number[];
  radius: number;
  depth: number;
  basin?: string;
}

export interface PondCompliance {
  basis: 'storage_capacity' | string;
  basin: string;
  storageCapacityM3: number;
  requiresPermit: boolean;
  permitThresholdM3: number;
  localSlopePct: number;
  breachRisk: 'low' | 'medium' | 'high' | string;
  downstreamExposure: {
    hasExposure: boolean;
    affectedBuildings: number;
    affectedRoads: number;
    affectedStreams: number;
  };
  disclaimer?: string;
}

export interface PondScoreResponse {
  pondScore: number;
  isViable: boolean;
  factors: Record<string, number>;
  compliance?: PondCompliance;
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

export interface ScenarioKpi {
  water_captured_m3: number;
  runoff_avoided_m3: number;
  sediment_retained_t: number;
  earthwork_m3: number;
  investment_eur: number;
  water_autonomy_pct: number;
  reliability_pct: number;
}

export interface RetentionYear {
  extraStoredM3: number;
  extraSummerDays: number;
  baselineSummerDays: number;
}

export interface ScenarioComparison {
  status?: 'ok' | 'no_data' | 'not_available' | string;
  mode?: CalculationMode | null;
  returnPeriodYears?: number | null;
  reason?: string;
  retention?: { median: RetentionYear; dry: RetentionYear };
  baseline?: ScenarioKpi;
  intervention?: ScenarioKpi;
  comparison?: Array<{ name: string } & ScenarioKpi>;
  designsConsidered?: number;
  capturedM3?: number;
  assumptions?: string;
}

export interface HydroAlert {
  severity: 'info' | 'warning' | 'critical' | string;
  mechanism: 'saturationExcess' | 'infiltrationExcess' | string;
  description: string;
}

export interface AlertResult {
  status?: 'ok' | 'no_data' | string;
  alerts?: HydroAlert[];
  inputs?: { soilSaturationPct: number; precipitationMm: number; slopeMean: number; ndvi: number };
}

export const api = {
  // DEM analysis (async job)
  analyzeParcel: (parcelId: string) =>
    post<AnalyzeResponse>(`/analyze/${encodeURIComponent(parcelId)}`, {}),
  getJob: (jobId: string) => get<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`),

  // Per-parcel calculation settings (PUT: technicians and admins only)
  getSettings: (parcelId: string) =>
    get<ParcelSettings>(`/parcels/${encodeURIComponent(parcelId)}/settings`),
  putSettings: (parcelId: string, mode: CalculationMode, returnPeriodYears: ReturnPeriod) =>
    put<ParcelSettings>(`/parcels/${encodeURIComponent(parcelId)}/settings`, {
      mode,
      return_period_years: returnPeriodYears,
    }),

  // Zones
  getZones: (parcelId: string) => get<ZoneKpi[]>(`/parcels/${encodeURIComponent(parcelId)}/zones`),

  // Parcel summary (latest AgriParcelRecord surfaced as flat KPIs)
  getSummary: (parcelId: string) =>
    get<ParcelSummary>(`/parcels/${encodeURIComponent(parcelId)}/summary`),

  // Scenario comparison (baseline vs intervention, on-demand from latest record + designs)
  getScenarios: (parcelId: string) =>
    get<ScenarioComparison>(`/parcels/${encodeURIComponent(parcelId)}/scenarios`),

  // Hydrologic alerts (reactive, on-demand from latest record)
  getAlerts: (parcelId: string) =>
    get<AlertResult>(`/parcels/${encodeURIComponent(parcelId)}/alerts`),

  // Visualization overlays (JSON through the same-origin gateway)
  getTwiOverlay: (parcelId: string) =>
    get<TwiOverlayResponse>(`/visualization/${encodeURIComponent(parcelId)}/overlay/twi`),
  getFlows: (parcelId: string) =>
    get<GeoJSON.FeatureCollection>(`/visualization/${encodeURIComponent(parcelId)}/flows`),

  // Design generation
  generateKeyline: (req: KeylineRequest) => post<KeylineResponse>('/design/keyline/generate', req),
  // Background layout: poll getJob(job_id); a finished job's result is a KeylineResponse.
  startKeylineJob: (req: KeylineRequest) =>
    post<{ job_id: string; status: string }>('/design/keyline/jobs', req),
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
