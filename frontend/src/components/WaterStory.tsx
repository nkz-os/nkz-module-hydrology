/**
 * Water Story 3D — Cesium overlay components.
 */

import { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import type { FeatureCollection } from 'geojson';

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'https://nkz.robotika.cloud';

interface Props {
  parcelId: string;
  twiUrl?: string;
  flows?: FeatureCollection;
}

/** TWI overlay as PMTiles. */
export function TWILayer({ parcelId }: { parcelId: string }) {
  const { cesiumViewer: viewer } = useViewer();
  const layerRef = useRef<any>(null);

  useEffect(() => {
    if (!viewer) return;
    (async () => {
      const resp = await fetch(`${API_BASE}/api/v1/hydrology/visualization/${parcelId}/tiles/twi`);
      const { url } = await resp.json();
      const provider = new (window as any).Cesium.CreateTileMapServiceImageryProvider({
        url,
        minimumLevel: 10,
        maximumLevel: 18,
      });
      const layer = viewer.imageryLayers.addImageryProvider(provider);
      layer.alpha = 0.6;
      layer.name = 'TWI (Water Studio)';
      layerRef.current = layer;
    })();
    return () => {
      if (layerRef.current) viewer.imageryLayers.remove(layerRef.current, true);
    };
  }, [viewer, parcelId]);

  return null;
}

/** Animated flow lines along drainage network. */
export function FlowAnimation({ parcelId, flows }: { parcelId: string; flows?: FeatureCollection }) {
  const { cesiumViewer: viewer } = useViewer();
  const entitiesRef = useRef<any[]>([]);

  useEffect(() => {
    if (!viewer || !flows?.features) return;
    const Cesium = (window as any).Cesium;
    const features = flows.features.filter(f => f.geometry?.type === 'LineString');

    for (const feat of features.slice(0, 50)) {
      const coords = (feat.geometry as any).coordinates;
      const positions = coords.map((c: number[]) => Cesium.Cartesian3.fromDegrees(c[0], c[1]));
      const entity = viewer.entities.add({
        polyline: {
          positions,
          width: 2,
          material: new Cesium.PolylineGlowMaterialProperty({
            glowPower: 0.2,
            color: Cesium.Color.fromCssColorString('#3B82F6').withAlpha(0.7),
          }),
        },
      });
      entitiesRef.current.push(entity);
    }
    return () => {
      entitiesRef.current.forEach(e => viewer.entities.remove(e));
      entitiesRef.current = [];
    };
  }, [viewer, flows]);

  return null;
}

/** KPI comparison panel. */
export function KPIPanel({ parcelId }: { parcelId: string }) {
  const [kpis, setKpis] = React.useState<any>(null);

  useEffect(() => {
    (async () => {
      const resp = await fetch(`${API_BASE}/api/v1/hydrology/visualization/${parcelId}/kpis`);
      setKpis(await resp.json());
    })();
  }, [parcelId]);

  if (!kpis) return <div className="nkz-panel p-3">Loading KPIs...</div>;

  const { baseline, intervention } = kpis;
  return (
    <div className="nkz-panel p-3 space-y-2">
      <h3 className="nkz-heading-sm">Scenario comparison</h3>
      <table className="nkz-table w-full text-sm">
        <thead>
          <tr><th>KPI</th><th>Baseline</th><th>With intervention</th></tr>
        </thead>
        <tbody>
          {[
            { label: 'Water captured', key: 'water_captured_m3', unit: 'm³' },
            { label: 'Sediment retained', key: 'sediment_retained_t', unit: 't' },
            { label: 'Earthwork', key: 'earthwork_m3', unit: 'm³' },
            { label: 'Investment', key: 'investment_eur', unit: '€' },
          ].map(row => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td>{(baseline as any)?.[row.key] ?? '-'}</td>
              <td>{(intervention as any)?.[row.key] ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
