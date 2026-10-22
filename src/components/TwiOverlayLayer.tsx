import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';

/**
 * TWI ground overlay (map-layer slot). Fetches a presigned PNG + WGS84 bounds
 * for the selected parcel and adds it as a single-tile imagery layer.
 *
 * ⚠️ The legacy `new SingleTileImageryProvider(...)` constructor is REMOVED in
 * current Cesium — MUST use the async static `fromUrl`. Async resolution is
 * race-guarded: if the component unmounts / hides / the parcel changes before
 * `fromUrl` resolves, the layer is never added (or is removed on cleanup).
 */
const TwiOverlayLayer: React.FC = () => {
  const { cesiumViewer: viewer, selectedEntityId: parcelId } = useViewer();
  const { twiVisible, twiOpacity, setTwiStatus } = useHydrologyLayerContext();
  const layerRef = useRef<any>(null);

  useEffect(() => {
    const Cesium = (window as any).Cesium;

    const removeLayer = () => {
      if (!layerRef.current) return;
      try {
        if (!viewer?.isDestroyed?.()) viewer.imageryLayers.remove(layerRef.current, true);
      } catch {
        /* viewer torn down */
      }
      layerRef.current = null;
    };

    removeLayer();

    if (!viewer || !parcelId || !twiVisible || !Cesium) {
      if (!twiVisible) setTwiStatus('idle');
      return;
    }

    let cancelled = false;
    setTwiStatus('loading');

    (async () => {
      try {
        const res = await api.getTwiOverlay(parcelId);
        if (cancelled) return;
        if (res.status === 'not_generated' || !res.url || !res.bounds) {
          setTwiStatus('not_generated');
          return;
        }
        const { west, south, east, north } = res.bounds;
        const provider = await Cesium.SingleTileImageryProvider.fromUrl(res.url, {
          rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
        });
        // Component may have unmounted / re-run while fromUrl was pending.
        if (cancelled || viewer.isDestroyed?.()) return;
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        if (layer) {
          layer.alpha = twiOpacity;
          layerRef.current = layer;
          setTwiStatus('ready');
        }
      } catch (err) {
        if (!cancelled) {
          console.error('[Hydrology] TWI overlay error:', err);
          setTwiStatus('error');
        }
      }
    })();

    return () => {
      cancelled = true;
      removeLayer();
    };
    // twiOpacity intentionally excluded: opacity changes are applied by the
    // effect below without re-fetching / re-adding the imagery layer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, parcelId, twiVisible, setTwiStatus]);

  useEffect(() => {
    if (layerRef.current) layerRef.current.alpha = twiOpacity;
  }, [twiOpacity]);

  return null;
};

export default TwiOverlayLayer;
