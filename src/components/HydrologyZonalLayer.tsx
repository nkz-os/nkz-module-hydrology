import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { api, ZoneKpi } from '../services/api';

interface Props {
  parcelId: string;
  activeKpi?: string;
  visible?: boolean;
}

const KPI_COLORS: Record<string, [number, number, number][]> = {
  runoffMm: [[51, 128, 255], [51, 255, 51], [255, 255, 51], [255, 128, 0], [255, 26, 26]],
  sedimentYieldTonnes: [[51, 128, 255], [51, 255, 51], [255, 255, 51], [255, 128, 0], [255, 26, 26]],
  soilSaturationPct: [[255, 77, 77], [255, 153, 51], [255, 255, 51], [153, 255, 77], [51, 128, 255]],
  pondViability: [[255, 26, 26], [255, 128, 0], [153, 255, 77]],
};

function interpolateColor(palette: [number, number, number][], t: number): [number, number, number] {
  const idx = Math.min(Math.floor(t * (palette.length - 1)), palette.length - 2);
  const frac = t * (palette.length - 1) - idx;
  return [
    Math.round(palette[idx][0] + (palette[idx + 1][0] - palette[idx][0]) * frac),
    Math.round(palette[idx][1] + (palette[idx + 1][1] - palette[idx][1]) * frac),
    Math.round(palette[idx][2] + (palette[idx + 1][2] - palette[idx][2]) * frac),
  ];
}

const HydrologyZonalLayer: React.FC<Props> = ({ parcelId, activeKpi = 'runoffMm', visible = true }) => {
  const { cesiumViewer: viewer } = useViewer();
  const entitiesRef = useRef<any[]>([]);

  useEffect(() => {
    if (!viewer || !visible) return;
    let cancelled = false;
    const Cesium = (window as any).Cesium;

    (async () => {
      try {
        const zones = await api.getZones(parcelId);
        if (cancelled || !zones.length) return;

        const values = zones.map((z: any) => (z as any)[activeKpi] ?? 0).filter((v: number) => v != null);
        const min = Math.min(...values);
        const max = Math.max(...values);
        const palette = KPI_COLORS[activeKpi] || KPI_COLORS.runoffMm;

        // Stub: zones don't have geometry yet from Plan A backend.
        // When backend returns GeoJSON polygons, render them.
        // For now, entities are placeholders.
        zones.forEach((zone: ZoneKpi) => {
          const val = (zone as any)[activeKpi] ?? 0;
          const t = max > min ? (val - min) / (max - min) : 0.5;
          const [r, g, b] = interpolateColor(palette, t);

          const entity = viewer.entities.add({
            name: zone.zoneId,
            description: `${activeKpi}: ${val.toFixed(1)}`,
            point: { pixelSize: 6, color: Cesium.Color.fromBytes(r, g, b, 102) },
          });
          entitiesRef.current.push(entity);
        });
      } catch (err) {
        console.error('[Hydrology] zonal layer error:', err);
      }
    })();

    return () => {
      cancelled = true;
      entitiesRef.current.forEach((e) => viewer?.entities.remove(e));
      entitiesRef.current = [];
    };
  }, [viewer, parcelId, activeKpi, visible]);

  return null;
};

export default HydrologyZonalLayer;
