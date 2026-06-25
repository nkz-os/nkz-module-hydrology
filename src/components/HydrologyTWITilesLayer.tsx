import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'https://nkz.robotika.cloud';

interface Props {
  parcelId: string;
  visible?: boolean;
}

const HydrologyTWITilesLayer: React.FC<Props> = ({ parcelId, visible = true }) => {
  const { cesiumViewer: viewer } = useViewer();
  const layerRef = useRef<any>(null);

  useEffect(() => {
    if (!viewer || !visible) return;

    (async () => {
      try {
        const Cesium = (window as any).Cesium;
        const tileUrl = `${API_BASE}/api/v1/hydrology/tiles/${encodeURIComponent(parcelId)}/{z}/{x}/{y}.png`;
        const provider = new Cesium.UrlTemplateImageryProvider({
          url: tileUrl,
          minimumLevel: 10,
          maximumLevel: 18,
        });
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = 0.7;
        layerRef.current = layer;
      } catch (err) {
        console.error('[Hydrology] TWI layer failed:', err);
      }
    })();

    return () => {
      if (layerRef.current) {
        viewer.imageryLayers.remove(layerRef.current);
        layerRef.current = null;
      }
    };
  }, [viewer, parcelId, visible]);

  return null;
};

export default HydrologyTWITilesLayer;
