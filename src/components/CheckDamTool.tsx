import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const CheckDamTool: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const [height, setHeight] = useState(1.5);
  const [width, setWidth] = useState(8.0);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const suggest = async () => {
    setLoading(true);
    try {
      const res = await api.suggestCheckDams({
        parcel_id: parcelId, height, width,
      });
      setResult(res);
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
      {result && <ExportMenu designType="check_dam" geometry={result} />}
    </div>
  );
};

export default CheckDamTool;
