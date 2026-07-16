import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import { DrawingManager } from './DrawingManager';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

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
        parcel_id: parcelId, center, radius, depth,
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
