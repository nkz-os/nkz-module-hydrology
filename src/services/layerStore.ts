/**
 * Shared hydrology layer state across the layer-toggle, map-layer and
 * context-panel slots. Each slot mounts in a separate React tree inside the
 * host viewer, so React context does NOT span them — mirror weather-map:
 * a plain module-scoped store consumed via useSyncExternalStore.
 */

/** TWI overlay lifecycle for the toggle to surface a hint (e.g. run analysis). */
export type TwiStatus = 'idle' | 'loading' | 'ready' | 'not_generated' | 'error';

export interface DesignGeometry {
  id: string;
  type: 'keyline' | 'pond' | 'swale' | 'check_dam';
  geometry: GeoJSON.Geometry;
  label?: string;
  /** Pond circle radius in metres (rendered as a clamped ellipse). */
  radius?: number;
}

export interface HydrologyLayerState {
  twiVisible: boolean;
  twiOpacity: number;
  twiStatus: TwiStatus;
  flowsVisible: boolean;
  designsVisible: boolean;
  designs: DesignGeometry[];
}

let state: HydrologyLayerState = {
  twiVisible: false,
  twiOpacity: 0.7,
  twiStatus: 'idle',
  flowsVisible: false,
  designsVisible: false,
  designs: [],
};

const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

export function getHydrologyLayerState(): HydrologyLayerState {
  return state;
}

export function setHydrologyLayerState(patch: Partial<HydrologyLayerState>): void {
  state = { ...state, ...patch };
  emit();
}

export function subscribeHydrologyLayer(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
