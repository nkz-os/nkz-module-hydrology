import React, { useCallback, useSyncExternalStore } from 'react';
import {
  getHydrologyLayerState,
  setHydrologyLayerState,
  subscribeHydrologyLayer,
  type HydrologyLayerState,
  type TwiStatus,
  type DesignGeometry,
} from './layerStore';

export type { TwiStatus, DesignGeometry };

interface HydrologyLayerControls extends HydrologyLayerState {
  setTwiVisible: (visible: boolean) => void;
  setTwiOpacity: (opacity: number) => void;
  setTwiStatus: (status: TwiStatus) => void;
  setFlowsVisible: (visible: boolean) => void;
  setDesignsVisible: (visible: boolean) => void;
  setDesigns: (designs: DesignGeometry[]) => void;
}

export function useHydrologyLayerContext(): HydrologyLayerControls {
  const snap = useSyncExternalStore(
    subscribeHydrologyLayer,
    getHydrologyLayerState,
    getHydrologyLayerState,
  );

  const setTwiVisible = useCallback((twiVisible: boolean) => setHydrologyLayerState({ twiVisible }), []);
  const setTwiOpacity = useCallback((twiOpacity: number) => setHydrologyLayerState({ twiOpacity }), []);
  const setTwiStatus = useCallback((twiStatus: TwiStatus) => setHydrologyLayerState({ twiStatus }), []);
  const setFlowsVisible = useCallback((flowsVisible: boolean) => setHydrologyLayerState({ flowsVisible }), []);
  const setDesignsVisible = useCallback(
    (designsVisible: boolean) => setHydrologyLayerState({ designsVisible }),
    [],
  );
  const setDesigns = useCallback((designs: DesignGeometry[]) => setHydrologyLayerState({ designs }), []);

  return {
    ...snap,
    setTwiVisible,
    setTwiOpacity,
    setTwiStatus,
    setFlowsVisible,
    setDesignsVisible,
    setDesigns,
  };
}

/** Passthrough kept for module-kit withModuleProvider; state lives in layerStore. */
export function HydrologyLayerProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
