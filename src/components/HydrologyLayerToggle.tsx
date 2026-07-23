import React from 'react';
import { useTranslation } from 'react-i18next';
import { useHydrologyLayerContext } from '../services/layerContext';

/**
 * Layer-toggle slot: drives the shared hydrology layer store (TWI overlay +
 * opacity, drainage network, designs). Mounts in its own React tree, so it
 * reads/writes the module-scoped store rather than props/context.
 */
const HydrologyLayerToggle: React.FC = () => {
  const { t } = useTranslation();
  const {
    twiVisible,
    twiOpacity,
    twiStatus,
    flowsVisible,
    zonesVisible,
    designsVisible,
    setTwiVisible,
    setTwiOpacity,
    setFlowsVisible,
    setZonesVisible,
    setDesignsVisible,
  } = useHydrologyLayerContext();

  const rowClass =
    'flex items-center gap-2 text-xs cursor-pointer hover:bg-white/5 px-1 py-0.5 rounded';

  return (
    <div className="hydrology-layer-toggle space-y-1">
      <label className={rowClass}>
        <input
          type="checkbox"
          checked={twiVisible}
          onChange={(e) => setTwiVisible(e.target.checked)}
          className="w-3.5 h-3.5"
        />
        <span className={twiVisible ? 'text-nkz-text' : 'text-nkz-muted'}>
          {t('hydrology:layerTwi')}
        </span>
      </label>

      {twiVisible && (
        <div className="pl-6 pr-1 space-y-0.5">
          <input
            type="range"
            min={0.2}
            max={1}
            step={0.05}
            value={twiOpacity}
            onChange={(e) => setTwiOpacity(Number(e.target.value))}
            className="w-full"
            aria-label={t('hydrology:opacity')}
          />
          {twiStatus === 'not_generated' && (
            <p className="text-[11px] text-nkz-muted">{t('hydrology:runAnalysis')}</p>
          )}
          {twiStatus === 'error' && (
            <p className="text-[11px] text-red-500">{t('hydrology:twiError')}</p>
          )}
        </div>
      )}

      <label className={rowClass}>
        <input
          type="checkbox"
          checked={flowsVisible}
          onChange={(e) => setFlowsVisible(e.target.checked)}
          className="w-3.5 h-3.5"
        />
        <span className={flowsVisible ? 'text-nkz-text' : 'text-nkz-muted'}>
          {t('hydrology:layerFlows')}
        </span>
      </label>

      <label className={rowClass}>
        <input
          type="checkbox"
          checked={zonesVisible}
          onChange={(e) => setZonesVisible(e.target.checked)}
          className="w-3.5 h-3.5"
        />
        <span className={zonesVisible ? 'text-nkz-text' : 'text-nkz-muted'}>
          {t('hydrology:layerZones')}
        </span>
      </label>

      <label className={rowClass}>
        <input
          type="checkbox"
          checked={designsVisible}
          onChange={(e) => setDesignsVisible(e.target.checked)}
          className="w-3.5 h-3.5"
        />
        <span className={designsVisible ? 'text-nkz-text' : 'text-nkz-muted'}>
          {t('hydrology:layerDesigns')}
        </span>
      </label>
    </div>
  );
};

export default HydrologyLayerToggle;
