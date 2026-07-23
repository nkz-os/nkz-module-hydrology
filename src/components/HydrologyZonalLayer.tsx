import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';

/**
 * Zonal KPI layer (map-layer slot). Fetches AgriParcelZone entities (with real
 * polygon geometry since Phase 1.1) and renders each TWI quintile zone as a
 * ground-clamped, semi-transparent polygon coloured from dry (tan) → wet (blue).
 *
 * Entities are removed on hide / unmount / parcel change. Defensive against
 * missing geometry (zones published before Phase 1.1 carried none).
 */
const ZONE_COLORS: Record<string, string> = {
  'twi-very-low': 'PERU',
  'twi-low': 'GOLD',
  'twi-medium': 'LIMEGREEN',
  'twi-high': 'DODGERBLUE',
  'twi-very-high': 'DEEPSKYBLUE',
};

const HydrologyZonalLayer: React.FC = () => {
  const { cesiumViewer: viewer, selectedEntityId: parcelId } = useViewer();
  const { zonesVisible } = useHydrologyLayerContext();
  const entitiesRef = useRef<any[]>([]);

  useEffect(() => {
    const clear = () => {
      entitiesRef.current.forEach((e) => {
        try {
          viewer?.entities.remove(e);
        } catch {
          /* viewer torn down */
        }
      });
      entitiesRef.current = [];
    };

    clear();
    if (!viewer || !parcelId || !zonesVisible) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    let cancelled = false;
    const colorFor = (zoneId: string) =>
      (Cesium.Color as any)[ZONE_COLORS[zoneId] || 'LIMEGREEN'] || Cesium.Color.LIMEGREEN;

    const addRing = (ring: number[][], zoneId: string) => {
      // GeoJSON Polygon ring = [ [lon, lat], ... ] (outer ring; holes ignored
      // for rendering clarity at this zoom).
      if (!ring || ring.length < 3) return;
      const color = colorFor(zoneId);
      const entity = viewer.entities.add({
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(ring.flat()),
          material: color.withAlpha(0.35),
          outline: true,
          outlineColor: color,
          classificationType: Cesium.ClassificationType.BOTH,
        },
      });
      entitiesRef.current.push(entity);
    };

    (async () => {
      try {
        const zones = await api.getZones(parcelId);
        if (cancelled || !zones?.length) return;
        zones.forEach((z) => {
          const g = z.geometry;
          if (!g || !g.type) return;
          if (g.type === 'Polygon') {
            // coordinates = [ outer, hole1, ... ]; render outer only.
            const outer = (g.coordinates as number[][][])[0];
            if (outer) addRing(outer, z.zoneId);
          } else if (g.type === 'MultiPolygon') {
            (g.coordinates as number[][][][]).forEach((poly) => {
              const outer = poly[0];
              if (outer) addRing(outer, z.zoneId);
            });
          }
        });
      } catch (err) {
        // No zones yet (DEM pipeline not run) or transient — non-fatal.
        if (!cancelled) console.error('[Hydrology] zones layer error:', err);
      }
    })();

    return () => {
      cancelled = true;
      clear();
    };
  }, [viewer, parcelId, zonesVisible]);

  return null;
};

export default HydrologyZonalLayer;
