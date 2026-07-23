import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import { DrawingManager } from './DrawingManager';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

// Basin authority codes (compliance permit thresholds). Proper nouns — no i18n.
const BASINS = [
  'default', 'CH_Ebro', 'CH_Duero', 'CH_Tajo', 'CH_Guadiana',
  'CH_Guadalquivir', 'CH_Segura', 'CH_Jucar', 'CH_Minho_Sil', 'CH_Cantabrico',
];

const PondSitingTool: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const { cesiumViewer } = useViewer();
  const { setDesigns, setDesignsVisible } = useHydrologyLayerContext();
  const [radius, setRadius] = useState(20);
  const [depth, setDepth] = useState(3);
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [label, setLabel] = useState('');
  const [savedId, setSavedId] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);
  const [basin, setBasin] = useState('default');
  const drawingRef = useRef<DrawingManager | null>(null);

  // Cancel any in-progress map drawing when the tool unmounts.
  useEffect(() => () => { drawingRef.current?.cancel(); }, []);

  const pickOnMap = () => {
    if (!cesiumViewer) return;
    drawingRef.current?.cancel();
    const dm = new DrawingManager(cesiumViewer);
    drawingRef.current = dm;
    dm.start('Point', {
      onComplete: (geom) => {
        if (geom.type === 'Point') {
          const coords = geom.coordinates as number[];
          setCenter([coords[0], coords[1]]);
        }
      },
    });
  };

  const score = async () => {
    if (!center) return;
    setLoading(true);
    setSavedId(undefined);
    try {
      const res = await api.scorePond({
        parcel_id: parcelId, center, radius, depth, basin,
      });
      setResult(res);

      if (res.isViable) {
        setDesigns([{
          id: 'pond',
          type: 'pond',
          geometry: { type: 'Point', coordinates: center },
          radius,
        }]);
        setDesignsVisible(true);
      }
    } catch (e) {
      console.error('Pond scoring failed:', e);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    if (!center || !result) return;
    setSaving(true);
    try {
      const { id } = await api.saveDesign({
        parcel_id: parcelId,
        design_type: 'pond',
        geometry: { type: 'Point', coordinates: center },
        parameters: {
          radius,
          depth,
          capacity: Math.PI * radius * radius * depth,
          pondScore: result.pondScore,
          isViable: result.isViable,
        },
        label: label || t('hydrology:pondSiting'),
      });
      setSavedId(id);
    } catch (e) {
      console.error('Pond save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-nkz-muted">{t('hydrology:pondSiting')}</p>
      {cesiumViewer ? (
        <button onClick={pickOnMap}
                className="border px-3 py-1 rounded text-sm w-full">
          {t('hydrology:pickOnMap')}
        </button>
      ) : (
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-nkz-muted">Lon</label>
            <input type="number" value={center?.[0] ?? ''}
                   onChange={(e) => setCenter([Number(e.target.value), center?.[1] ?? 0])}
                   className="w-full border rounded px-2 py-1 text-sm" />
          </div>
          <div className="flex-1">
            <label className="text-xs text-nkz-muted">Lat</label>
            <input type="number" value={center?.[1] ?? ''}
                   onChange={(e) => setCenter([center?.[0] ?? 0, Number(e.target.value)])}
                   className="w-full border rounded px-2 py-1 text-sm" />
          </div>
        </div>
      )}
      {center && (
        <p className="text-xs text-nkz-muted">
          {t('hydrology:centerPicked')}: {center[0].toFixed(5)}, {center[1].toFixed(5)}
        </p>
      )}
      <div>
        <label className="text-xs text-nkz-muted">Radius (m)</label>
        <input type="number" value={radius} onChange={(e) => setRadius(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">Depth (m)</label>
        <input type="number" value={depth} onChange={(e) => setDepth(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">{t('hydrology:basin')}</label>
        <select value={basin} onChange={(e) => setBasin(e.target.value)}
                className="w-full border rounded px-2 py-1 text-sm">
          {BASINS.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>
      <button onClick={score} disabled={loading || !center}
              className="bg-nkz-accent text-white px-3 py-1 rounded text-sm w-full disabled:opacity-60">
        {loading ? t('hydrology:loading') : t('hydrology:pondViability')}
      </button>
      {result && center && (
        <div className="text-xs">
          <p>{t('hydrology:pondViability')}: {result.pondScore?.toFixed(2)}</p>
          <p className={result.isViable ? 'text-green-600' : 'text-red-500'}>
            {result.isViable ? t('hydrology:viable') : t('hydrology:notViable')}
          </p>
          {result.compliance && (
            <div className="mt-1 p-2 border border-nkz-border rounded">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                  result.compliance.breachRisk === 'high' ? 'bg-red-500/15 text-red-500' :
                  result.compliance.breachRisk === 'medium' ? 'bg-amber-500/15 text-amber-500' :
                  'bg-green-500/15 text-green-500'
                }`}>
                  {t(`hydrology:breach_${result.compliance.breachRisk}`)}
                </span>
                <span className={result.compliance.requiresPermit ? 'text-red-500' : 'text-green-600'}>
                  {result.compliance.requiresPermit ? t('hydrology:permitRequired') : t('hydrology:noPermitRequired')}
                </span>
              </div>
              <p className="text-[10px] text-nkz-muted mt-1">
                {t('hydrology:complianceDetail', {
                  capacity: result.compliance.storageCapacityM3,
                  threshold: result.compliance.permitThresholdM3,
                })}
              </p>
              <p className="text-[10px] text-nkz-muted mt-1 italic">
                {t('hydrology:complianceDisclaimer')}
              </p>
            </div>
          )}
          <div className="flex gap-1 pt-1">
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('hydrology:designLabel')}
              className="flex-1 border rounded px-2 py-1 text-sm"
            />
            <button onClick={save} disabled={saving}
                    className="border px-3 py-1 rounded text-sm whitespace-nowrap disabled:opacity-60">
              {saving ? t('hydrology:loading') : savedId ? t('hydrology:saved') : t('hydrology:save')}
            </button>
          </div>
          <ExportMenu designType="pond" geometry={{ type: 'Point', coordinates: center }} designId={savedId} />
        </div>
      )}
    </div>
  );
};

export default PondSitingTool;
