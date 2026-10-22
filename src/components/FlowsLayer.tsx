import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';

/**
 * Drainage network (map-layer slot). Fetches the stream-line GeoJSON for the
 * selected parcel and renders LineStrings as ground-clamped polylines.
 * Entities are removed on hide / unmount / parcel change.
 */
const FlowsLayer: React.FC = () => {
  const { cesiumViewer: viewer, selectedEntityId: parcelId } = useViewer();
  const { flowsVisible } = useHydrologyLayerContext();
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

    if (!viewer || !parcelId || !flowsVisible) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    let cancelled = false;

    const addLine = (coords: number[][]) => {
      const flat = coords.flat();
      if (flat.length < 4) return;
      const entity = viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          material: Cesium.Color.DODGERBLUE,
          width: 2,
          clampToGround: true,
        },
      });
      entitiesRef.current.push(entity);
    };

    (async () => {
      try {
        const fc = await api.getFlows(parcelId);
        if (cancelled || !fc?.features?.length) return;
        fc.features.forEach((f) => {
          const g = f.geometry;
          if (!g) return;
          if (g.type === 'LineString') addLine(g.coordinates as number[][]);
          else if (g.type === 'MultiLineString') {
            (g.coordinates as number[][][]).forEach(addLine);
          }
        });
      } catch (err) {
        // 404 = no flow data yet (DEM pipeline not run); non-fatal.
        if (!cancelled) console.error('[Hydrology] flows layer error:', err);
      }
    })();

    return () => {
      cancelled = true;
      clear();
    };
  }, [viewer, parcelId, flowsVisible]);

  return null;
};

export default FlowsLayer;
