/**
 * Slot definitions — declare which host slots this module occupies.
 *
 * Each entry is `{ id, component, priority? }` where `component` is the
 * actual React component reference. The module-kit translates this into
 * the runtime SlotWidgetDefinition shape automatically.
 *
 * Available slot types:
 *   map-layer         — overlay or toolbar button on the 3D map
 *   layer-toggle      — toggle entry in the layer panel
 *   context-panel     — side panel shown when an entity is selected
 *   bottom-panel      — tabbed panel at the bottom of the viewer
 *   entity-tree       — context menu entry in the entity tree
 *   dashboard-widget  — card in the tenant dashboard
 */
import { ExampleSlot } from '../components/slots/ExampleSlot';

export const moduleSlots = {
  'context-panel': [
    {
      id: 'hydrology-context',
      component: ExampleSlot,
      priority: 10,
    },
  ],
};
