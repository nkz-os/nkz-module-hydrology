/**
 * Single declarative source of truth for this module.
 *
 * `defineModule` is consumed by:
 *   - @nekazari/module-builder — generates moduleEntry + dist/manifest.json
 *   - the host runtime — registers route, slots, navigation, permissions
 *   - `nkz dev` — wires the dev shell against MockProvider
 *
 * Replace the MODULE_ placeholders below and delete this comment.
 */
import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import { moduleSlots } from './slots';
import pkg from '../package.json';

const MainPage = lazy(() => import('./App'));

export default defineModule({
  // === Identity ===
  id: 'hydrology',
  displayName: 'NKZ Water Studio',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  description: 'NKZ Water Studio — watershed delineation, DEM analysis, and hydrological modeling for precision agriculture.',

  // === UI ===
  accent: { base: '#06B6D4', soft: '#CFFAFE', strong: '#0891B2' },
  icon: 'droplets',
  main: MainPage,

  // === Host integration ===
  route: '/hydrology',
  navigation: {
    section: 'modules',
    priority: 45,
  },
  slots: moduleSlots as never,

  // === Backend ===
  api: { basePath: '/api/v1/hydrology' },

  // === Permissions ===
  requiredRoles: ['Farmer', 'TenantAdmin', 'PlatformAdmin'],
  requiredPlan: 'basic',

  // === Data dependencies (CSP-of-data enforced by the api-gateway) ===
  // Declare the NGSI-LD entity types and Timescale hypertables this module
  // reads/writes. The gateway will block requests for anything else.
  // Use ['*'] as wildcard to opt out (not recommended for production).
  data: {
    entities: ['AgriParcelRecord', 'AgriParcelZone', 'nkz:HydrologyDesign'],
    timeseries: ['AgriParcelRecord'],
  },
});
