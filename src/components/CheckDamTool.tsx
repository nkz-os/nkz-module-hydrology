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

  const suggest = async () => {
    setLoading(true);
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
        <ExportMenu
          designType="check_dam"
          geometry={{ type: 'MultiPoint', coordinates: result.dams.map((d: any) => d.coordinates) }}
        />
      )}
    </div>
  );
};

export default CheckDamTool;
