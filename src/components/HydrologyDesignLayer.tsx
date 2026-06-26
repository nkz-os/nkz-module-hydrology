import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';

export interface DesignGeometry {
  id: string;
  type: 'keyline' | 'pond' | 'swale' | 'check_dam';
  geometry: GeoJSON.Geometry;
  label?: string;
}

interface Props {
  designs: DesignGeometry[];
  visible?: boolean;
}

const TYPE_COLORS: Record<string, string> = {
  keyline: 'WHITE',
  swale: 'SANDY_BROWN',
  check_dam: 'ORANGE',
  pond: 'DODGERBLUE',
};

const HydrologyDesignLayer: React.FC<Props> = ({ designs = [], visible = true }) => {
  const { cesiumViewer: viewer } = useViewer();
  const entitiesRef = useRef<any[]>([]);

  useEffect(() => {
    if (!viewer || !visible) return;
    const Cesium = (window as any).Cesium;

    // Clear previous
    entitiesRef.current.forEach((e) => viewer.entities.remove(e));
    entitiesRef.current = [];

    designs.forEach((d) => {
      const colorName = TYPE_COLORS[d.type] || 'WHITE';

      if (d.geometry.type === 'LineString') {
        const coords = (d.geometry as GeoJSON.LineString).coordinates as number[][];
        const flat = coords.flat();
        const entity = viewer.entities.add({
          name: d.label || d.id,
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(flat),
            material: (Cesium.Color as any)[colorName],
            width: d.type === 'keyline' ? 2 : 1,
          },
        });
        entitiesRef.current.push(entity);
      } else if (d.geometry.type === 'MultiLineString') {
        const lines = (d.geometry as GeoJSON.MultiLineString).coordinates as number[][][];
        lines.forEach((coords) => {
          const flat = coords.flat();
          const entity = viewer.entities.add({
            name: d.label || d.id,
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(flat),
              material: (Cesium.Color as any)[colorName],
              width: d.type === 'keyline' ? 2 : 1,
            },
          });
          entitiesRef.current.push(entity);
        });
      } else if (d.geometry.type === 'Polygon') {
        const rings = (d.geometry as GeoJSON.Polygon).coordinates as number[][][];
        const outer = rings[0].flat();
        const entity = viewer.entities.add({
          name: d.label || d.id,
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(outer),
            material: (Cesium.Color as any)[colorName].withAlpha(0.3),
            outline: true,
            outlineColor: (Cesium.Color as any)[colorName],
          },
        });
        entitiesRef.current.push(entity);
      }
    });

    return () => {
      entitiesRef.current.forEach((e) => viewer.entities.remove(e));
    };
  }, [viewer, designs, visible]);

  return null;
};

export default HydrologyDesignLayer;
