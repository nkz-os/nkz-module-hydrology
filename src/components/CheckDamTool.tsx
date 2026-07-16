import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const CheckDamTool: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const { setDesigns, setDesignsVisible } = useHydrologyLayerContext();
  const [height, setHeight] = useState(1.5);
  const [width, setWidth] = useState(8.0);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [label, setLabel] = useState('');
  const [savedId, setSavedId] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);

  const suggest = async () => {
    setLoading(true);
    setSavedId(undefined);
    try {
      const res = await api.suggestCheckDams({
        parcel_id: parcelId, height, width,
      }) as { dams?: Array<{ coordinates: number[] }> };
      setResult(res);

      if (res.dams?.length) {
        setDesigns([{
          id: 'check-dam',
          type: 'check_dam',
          geometry: { type: 'MultiPoint', coordinates: res.dams.map((d) => d.coordinates) },
        }]);
        setDesignsVisible(true);
      }
    } catch (e) {
      console.error('Check dam suggestion failed:', e);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    if (!result?.dams?.length) return;
    setSaving(true);
    try {
      const { id } = await api.saveDesign({
        parcel_id: parcelId,
        design_type: 'check_dam',
        geometry: {
          type: 'MultiPoint',
          coordinates: result.dams.map((d: any) => d.coordinates),
        },
        parameters: { height, width },
        label: label || t('hydrology:checkDam'),
      });
      setSavedId(id);
    } catch (e) {
      console.error('Check dam save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <div>
        <label className="text-xs text-nkz-muted">Height (m)</label>
        <input type="number" value={height} onChange={(e) => setHeight(Number(e.target.value))} step={0.5}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">Width (m)</label>
        <input type="number" value={width} onChange={(e) => setWidth(Number(e.target.value))} step={0.5}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <button onClick={suggest} disabled={loading}
              className="bg-nkz-accent text-white px-3 py-1 rounded text-sm w-full">
        {loading ? t('hydrology:loading') : t('hydrology:checkDam')}
      </button>
      {result && result.dams?.length > 0 && (
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
            designType="check_dam"
            geometry={{ type: 'MultiPoint', coordinates: result.dams.map((d: any) => d.coordinates) }}
            designId={savedId}
          />
        </>
      )}
    </div>
  );
};

export default CheckDamTool;
