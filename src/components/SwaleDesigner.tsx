import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const SwaleDesigner: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const { setDesigns, setDesignsVisible } = useHydrologyLayerContext();
  const [bankHeight, setBankHeight] = useState(0.5);
  const [trenchDepth, setTrenchDepth] = useState(1.0);
  const [trenchWidth, setTrenchWidth] = useState(2.0);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [label, setLabel] = useState('');
  const [savedId, setSavedId] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);

  const suggest = async () => {
    setLoading(true);
    setSavedId(undefined);
    try {
      const res = await api.suggestSwales({
        parcel_id: parcelId, bank_height: bankHeight, trench_depth: trenchDepth, trench_width: trenchWidth,
      }) as { lines?: Array<{ coordinates: number[][] }> };
      setResult(res);

      if (res.lines?.length) {
        setDesigns([{
          id: 'swale',
          type: 'swale',
          geometry: { type: 'MultiLineString', coordinates: res.lines.map((l) => l.coordinates) },
        }]);
        setDesignsVisible(true);
      }
    } catch (e) {
      console.error('Swale suggestion failed:', e);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    if (!result?.lines?.length) return;
    setSaving(true);
    try {
      const { id } = await api.saveDesign({
        parcel_id: parcelId,
        design_type: 'swale',
        geometry: {
          type: 'MultiLineString',
          coordinates: result.lines.map((l: any) => l.coordinates),
        },
        parameters: { bank_height: bankHeight, trench_depth: trenchDepth, trench_width: trenchWidth },
        label: label || t('hydrology:swaleDesigner'),
      });
      setSavedId(id);
    } catch (e) {
      console.error('Swale save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <div>
        <label className="text-xs text-nkz-muted">Bank height (m)</label>
        <input type="number" value={bankHeight} onChange={(e) => setBankHeight(Number(e.target.value))} step={0.1}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">Trench depth (m)</label>
        <input type="number" value={trenchDepth} onChange={(e) => setTrenchDepth(Number(e.target.value))} step={0.1}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">Trench width (m)</label>
        <input type="number" value={trenchWidth} onChange={(e) => setTrenchWidth(Number(e.target.value))} step={0.5}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <button onClick={suggest} disabled={loading}
              className="bg-nkz-accent text-white px-3 py-1 rounded text-sm w-full">
        {loading ? t('hydrology:loading') : t('hydrology:swaleDesigner')}
      </button>
      {result && result.lines?.length > 0 && (
        <>
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
          <ExportMenu
            designType="swale"
            geometry={{ type: 'MultiLineString', coordinates: result.lines.map((l: any) => l.coordinates) }}
            designId={savedId}
          />
        </>
      )}
    </div>
  );
};

export default SwaleDesigner;
