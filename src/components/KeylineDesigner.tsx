import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import type { DesignGeometry } from '../services/layerStore';
import ExportMenu from './ExportMenu';

interface Props { parcelId: string; }

const KeylineDesigner: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const { setDesigns, setDesignsVisible } = useHydrologyLayerContext();
  const [grade, setGrade] = useState(0.5);
  const [spacing, setSpacing] = useState(12);
  const [lines, setLines] = useState(7);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    setLoading(true);
    try {
      const res = await api.generateKeyline({
        parcel_id: parcelId, grade: grade / 100, spacing, lines,
      });
      setResult(res);

      const geoms: DesignGeometry[] = [];
      if (res.keyline) {
        geoms.push({
          id: 'keyline-primary',
          type: 'keyline',
          geometry: res.keyline,
          label: t('hydrology:primaryKeyline'),
        });
      }
      (res.parallel_lines || []).forEach((p, i) => {
        geoms.push({ id: `keyline-parallel-${i}`, type: 'keyline', geometry: p.geometry });
      });
      setDesigns(geoms);
      setDesignsVisible(true);
    } catch (e) {
      console.error('Keyline generation failed:', e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <div>
        <label className="text-xs text-nkz-muted">{t('hydrology:grade')} ({grade}%)</label>
        <input type="range" min={0.1} max={2} step={0.1} value={grade}
               onChange={(e) => setGrade(Number(e.target.value))}
               className="w-full" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">{t('hydrology:spacing')}</label>
        <input type="number" value={spacing} onChange={(e) => setSpacing(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">{t('hydrology:lines')}</label>
        <input type="number" value={lines} onChange={(e) => setLines(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <button onClick={generate} disabled={loading}
              className="bg-nkz-accent text-white px-3 py-1 rounded text-sm w-full">
        {loading ? t('hydrology:loading') : t('hydrology:keypoint')}
      </button>
      {result && <ExportMenu designType="keyline" geometry={result.keyline} />}
    </div>
  );
};

export default KeylineDesigner;
