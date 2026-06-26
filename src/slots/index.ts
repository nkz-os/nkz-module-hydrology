import { lazy } from 'react';

export const moduleSlots = {
  'map-layer': [
    {
      id: 'hydrology-zonal',
      moduleId: 'hydrology',
      component: 'HydrologyZonalLayer',
      localComponent: lazy(() => import('../components/HydrologyZonalLayer')),
      priority: 15,
    },
    {
      id: 'hydrology-design',
      moduleId: 'hydrology',
      component: 'HydrologyDesignLayer',
      localComponent: lazy(() => import('../components/HydrologyDesignLayer')),
      priority: 20,
    },
  ],
  'layer-toggle': [
    {
      id: 'hydrology-toggle',
      moduleId: 'hydrology',
      component: 'HydrologyLayerToggle',
      localComponent: lazy(() => import('../components/HydrologyLayerToggle')),
      priority: 15,
    },
  ],
  'context-panel': [
    {
      id: 'hydrology-panel',
      moduleId: 'hydrology',
      component: 'HydrologyContextPanel',
      localComponent: lazy(() => import('../components/HydrologyContextPanel')),
      priority: 15,
      showWhen: { entityType: ['AgriParcel'] },
    },
  ],
};
