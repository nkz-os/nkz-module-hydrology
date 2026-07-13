import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const SwaleDesigner: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const [bankHeight, setBankHeight] = useState(0.5);
  const [trenchDepth, setTrenchDepth] = useState(1.0);
  const [trenchWidth, setTrenchWidth] = useState(2.0);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const suggest = async () => {
    setLoading(true);
    try {
      const res = await api.suggestSwales({
        parcel_id: parcelId, bank_height: bankHeight, trench_depth: trenchDepth, trench_width: trenchWidth,
      });
      setResult(res);
    } catch (e) {
      console.error('Swale suggestion failed:', e);
    } finally {
      setLoading(false);
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
        <ExportMenu
          designType="swale"
          geometry={{ type: 'MultiLineString', coordinates: result.lines.map((l: any) => l.coordinates) }}
        />
      )}
    </div>
  );
};

export default SwaleDesigner;
