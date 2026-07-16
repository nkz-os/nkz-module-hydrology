import React from 'react';

interface Props {
  parcelId?: string;
  activeKpi?: string;
  visible?: boolean;
}

/**
 * Zonal KPI layer — intentionally renders nothing.
 *
 * Zones (ZoneKpi) carry no geometry yet from the backend (spec Fase 2-4), so
 * the previous position-less Point stub only added invisible entities to the
 * viewer. The component stays mounted (returning null) to keep the map-layer
 * slot contract; once zones expose GeoJSON polygons, render them here.
 */
const HydrologyZonalLayer: React.FC<Props> = () => null;

export default HydrologyZonalLayer;
