import { API_ORIGIN } from './api';

// Same API origin as api.ts: the session cookie only travels to the API host.
const ROUTING_BASE = `${API_ORIGIN}/api/routing`;

export async function exportToGisRouting(geojson: Record<string, unknown>): Promise<void> {
  const resp = await fetch(`${ROUTING_BASE}/zones/external/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'geojson', content: JSON.stringify(geojson) }),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`GIS-routing export failed: HTTP ${resp.status}`);
}
