const API_BASE = (import.meta as any).env?.VITE_API_URL || 'https://nkz.robotika.cloud';
const HYDRO_BASE = `${API_BASE}/api/v1/hydrology`;

// Auth: the host exposes window.__nekazariAuthContext; inject the Keycloak
// Bearer token so the api-gateway accepts the request (cookies are not used).
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const ctx = typeof window !== 'undefined' ? (window as any).__nekazariAuthContext : undefined;
  const token = ctx?.getToken?.() || ctx?.token;
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
  await fetch(`${HYDRO_BASE}${path}`, { method: 'DELETE', headers: authHeaders(), credentials: 'include' });
}

export interface ZoneKpi {
  id: string;
  zoneId: string;
  twiMean: number;
  twiRange: string;
  areaHa: number;
  runoffMm?: number;
  sedimentYieldTonnes?: number;
  soilSaturationPct?: number;
  pondViability?: number;
  keylineGrade?: number;
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

export interface DesignSaveRequest {
  parcel_id: string;
  design_type: 'keyline' | 'pond' | 'swale' | 'check_dam';
  geometry: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  label?: string;
}

export const api = {
  // Zones
  getZones: (parcelId: string) => get<ZoneKpi[]>(`/parcels/${encodeURIComponent(parcelId)}/zones`),

  // Design generation
  generateKeyline: (req: KeylineRequest) => post<KeylineResponse>('/design/keyline/generate', req),
  scorePond: (req: PondScoreRequest) => post<PondScoreResponse>('/design/pond/score', req),
  suggestSwales: (req: SwaleSuggestRequest) => post('/design/swale/suggest', req),
  suggestCheckDams: (req: CheckDamSuggestRequest) => post('/design/check-dam/suggest', req),

  // Design CRUD
  listDesigns: (parcelId: string) => get(`/design?parcel_id=${encodeURIComponent(parcelId)}`),
  saveDesign: (req: DesignSaveRequest) => post('/design', req),
  getDesign: (id: string) => get(`/design/${encodeURIComponent(id)}`),
  updateDesign: (id: string, req: DesignSaveRequest) => put(`/design/${encodeURIComponent(id)}`, req),
  deleteDesign: (id: string) => del(`/design/${encodeURIComponent(id)}`),

  // Export
  getExportUrl: (designId: string, format: 'gpx' | 'kml' | 'geojson') =>
    `${HYDRO_BASE}/design/${encodeURIComponent(designId)}/export?format=${format}`,
};
