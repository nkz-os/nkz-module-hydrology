// Relative, same-origin path: mirrors api.ts — the frontend host proxies /api/*
// to the gateway and the httpOnly auth cookie only travels same-origin. An
// absolute cross-origin host would drop the cookie -> 401.
const ROUTING_BASE = '/api/routing';

export async function exportToGisRouting(geojson: Record<string, unknown>): Promise<void> {
  const resp = await fetch(`${ROUTING_BASE}/zones/external/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'geojson', content: JSON.stringify(geojson) }),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`GIS-routing export failed: HTTP ${resp.status}`);
}
