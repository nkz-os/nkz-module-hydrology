const ROUTING_BASE = (import.meta as any).env?.VITE_API_URL
  ? `${(import.meta as any).env.VITE_API_URL}/api/routing`
  : 'https://nkz.robotika.cloud/api/routing';

export async function exportToGisRouting(geojson: Record<string, unknown>): Promise<void> {
  const resp = await fetch(`${ROUTING_BASE}/zones/external/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'geojson', content: JSON.stringify(geojson) }),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`GIS-routing export failed: HTTP ${resp.status}`);
}
