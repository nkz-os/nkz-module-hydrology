import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const PondSitingTool: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const [radius, setRadius] = useState(20);
  const [depth, setDepth] = useState(3);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const score = async () => {
    setLoading(true);
    try {
      const res = await api.scorePond({
        parcel_id: parcelId, center: [0, 0], radius, depth,
      });
      setResult(res);
    } catch (e) {
      console.error('Pond scoring failed:', e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-nkz-muted">{t('hydrology:pondSiting')}</p>
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
      <button onClick={score} disabled={loading}
              className="bg-nkz-accent text-white px-3 py-1 rounded text-sm w-full">
        {loading ? t('hydrology:loading') : t('hydrology:pondViability')}
      </button>
      {result && (
        <div className="text-xs">
          <p>{t('hydrology:pondViability')}: {result.pondScore?.toFixed(2)}</p>
          <p className={result.isViable ? 'text-green-600' : 'text-red-500'}>
            {result.isViable ? t('hydrology:viable') : t('hydrology:notViable')}
          </p>
          <ExportMenu designType="pond" geometry={{ type: 'Point', coordinates: [0, 0] }} />
        </div>
      )}
    </div>
  );
};

export default PondSitingTool;
