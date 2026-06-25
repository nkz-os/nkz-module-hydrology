export const moduleSlots = {
  'map-layer': [
    {
      id: 'hydrology-zonal',
      moduleId: 'hydrology',
      component: 'HydrologyZonalLayer',
      localComponent: () => import('../components/HydrologyZonalLayer'),
      priority: 15,
    },
    {
      id: 'hydrology-design',
      moduleId: 'hydrology',
      component: 'HydrologyDesignLayer',
      localComponent: () => import('../components/HydrologyDesignLayer'),
      priority: 20,
    },
  ],
  'layer-toggle': [
    {
      id: 'hydrology-toggle',
      moduleId: 'hydrology',
      component: 'HydrologyLayerToggle',
      localComponent: () => import('../components/HydrologyLayerToggle'),
      priority: 15,
    },
  ],
  'context-panel': [
    {
      id: 'hydrology-panel',
      moduleId: 'hydrology',
      component: 'HydrologyContextPanel',
      localComponent: () => import('../components/HydrologyContextPanel'),
      priority: 15,
      showWhen: { entityType: ['AgriParcel'] },
    },
  ],
};
