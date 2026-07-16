import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { useHydrologyLayerContext } from '../services/layerContext';
import type { DesignGeometry } from '../services/layerStore';

export type { DesignGeometry };

interface Props {
  /** Optional override (tests); falls back to the shared layer store. */
  designs?: DesignGeometry[];
  visible?: boolean;
}

const TYPE_COLORS: Record<string, string> = {
  keyline: 'WHITE',
  swale: 'SANDY_BROWN',
  check_dam: 'ORANGE',
  pond: 'DODGERBLUE',
};

const HydrologyDesignLayer: React.FC<Props> = (props) => {
  const { cesiumViewer: viewer } = useViewer();
  const store = useHydrologyLayerContext();
  const designs = props.designs ?? store.designs;
  const visible = props.visible ?? store.designsVisible;
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
    if (!viewer || !visible) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const color = (name: string) => (Cesium.Color as any)[name] || Cesium.Color.WHITE;

    const addPolyline = (flat: number[], colorName: string, width: number) => {
      if (flat.length < 4) return;
      const entity = viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          material: color(colorName),
          width,
          clampToGround: true,
        },
      });
      entitiesRef.current.push(entity);
    };

    const addPoint = (coord: number[], colorName: string) => {
      if (coord.length < 2) return;
      const entity = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(coord[0], coord[1]),
        point: {
          pixelSize: 10,
          color: color(colorName),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      entitiesRef.current.push(entity);
    };

    designs.forEach((d) => {
      const colorName = TYPE_COLORS[d.type] || 'WHITE';
      const g = d.geometry;

      // Pond: center point + a ground-clamped circle at the scored radius.
      if (d.type === 'pond' && g.type === 'Point') {
        const coord = g.coordinates as number[];
        if (d.radius && coord.length >= 2) {
          const ellipse = viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(coord[0], coord[1]),
            ellipse: {
              semiMajorAxis: d.radius,
              semiMinorAxis: d.radius,
              material: color(colorName).withAlpha(0.35),
              outline: true,
              outlineColor: color(colorName),
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
          });
          entitiesRef.current.push(ellipse);
        }
        addPoint(coord, colorName);
        return;
      }

      switch (g.type) {
        case 'LineString':
          addPolyline((g.coordinates as number[][]).flat(), colorName, d.type === 'keyline' ? 2 : 1);
          break;
        case 'MultiLineString':
          (g.coordinates as number[][][]).forEach((line) =>
            addPolyline(line.flat(), colorName, d.type === 'keyline' ? 2 : 1),
          );
          break;
        case 'Point':
          addPoint(g.coordinates as number[], colorName);
          break;
        case 'MultiPoint':
          (g.coordinates as number[][]).forEach((c) => addPoint(c, colorName));
          break;
        case 'Polygon': {
          const outer = (g.coordinates as number[][][])[0].flat();
          const entity = viewer.entities.add({
            name: d.label || d.id,
            polygon: {
              hierarchy: Cesium.Cartesian3.fromDegreesArray(outer),
              material: color(colorName).withAlpha(0.3),
              outline: true,
              outlineColor: color(colorName),
            },
          });
          entitiesRef.current.push(entity);
          break;
        }
        default:
          break;
      }
    });

    return () => {
      clear();
    };
  }, [viewer, designs, visible]);

  return null;
};

export default HydrologyDesignLayer;
