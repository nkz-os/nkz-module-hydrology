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
  const [lines, setLines] = useState('');
  const [minLine, setMinLine] = useState(100);
  const [error, setError] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [label, setLabel] = useState('');
  const [savedId, setSavedId] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);
  // Parameters of the last generation: a save stores the values its lines
  // were generated with, not what the inputs hold now.
  const [sentParams, setSentParams] = useState<{ grade: number; spacing: number; lines: number | null; min_line_m: number } | null>(null);

  const linesValue = lines.trim() === '' || !(Number(lines) > 0) ? null : Math.floor(Number(lines));
  const minLineValue = minLine > 0 ? minLine : 100;

  const statusMessage = (): string | null => {
    if (error) return t('hydrology:keylineError');
    switch (result?.status) {
      case 'no_keypoint': return t('hydrology:keylineNoKeypoint');
      case 'terrain_too_coarse':
        return t('hydrology:keylineTerrainTooCoarse', {
          cell: result.cell_size_m != null ? result.cell_size_m.toFixed(1) : '?',
          max: result.max_cell_size_m ?? 5,
        });
      case 'no_data': return t('hydrology:keylineNoData');
      default: return null;
    }
  };
  const message = statusMessage();
  // Keylines (main valley's when only the singular field is set) and every
  // pattern line. A pattern may hold guides only, with no keyline at all.
  const keylineGeoms: any[] = result?.keylines?.length ? result.keylines : result?.keyline ? [result.keyline] : [];
  const patternGeoms: any[] = (result?.parallel_lines || []).map((p: any) => p.geometry);
  const hasLines = result?.status === 'ok' && keylineGeoms.length + patternGeoms.length > 0;

  const generate = async () => {
    setLoading(true);
    setSavedId(undefined);
    setError(false);
    setResult(null);
    setSentParams(null);
    const params = { grade: grade / 100, spacing, lines: linesValue, min_line_m: minLineValue };
    try {
      const res = await api.generateKeyline({ parcel_id: parcelId, ...params });
      setResult(res);
      setSentParams(params);

      const geoms: DesignGeometry[] = [];
      const mains = res.keylines?.length ? res.keylines : res.keyline ? [res.keyline] : [];
      mains.forEach((g, i) => {
        geoms.push({
          id: `keyline-primary-${i}`,
          type: 'keyline',
          geometry: g,
          label: t('hydrology:primaryKeyline'),
        });
      });
      const points = res.keypoints?.length ? res.keypoints : res.keypoint ? [res.keypoint] : [];
      points.forEach((g, i) => {
        geoms.push({ id: `keypoint-${i}`, type: 'keyline', geometry: g, label: t('hydrology:keypoint') });
      });
      (res.parallel_lines || []).forEach((p, i) => {
        geoms.push({ id: `keyline-parallel-${i}`, type: 'keyline', geometry: p.geometry });
      });
      setDesigns(geoms);
      setDesignsVisible(true);
    } catch (e) {
      console.error('Keyline generation failed:', e);
      setDesigns([]);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    if (!hasLines || !sentParams) return;
    const coordinates: number[][][] = [...keylineGeoms, ...patternGeoms].map((g: any) => g.coordinates);
    setSaving(true);
    try {
      const { id } = await api.saveDesign({
        parcel_id: parcelId,
        design_type: 'keyline',
        geometry: { type: 'MultiLineString', coordinates },
        parameters: sentParams,
        label: label || t('hydrology:keylineDesigner'),
      });
      setSavedId(id);
    } catch (e) {
      console.error('Keyline save failed:', e);
    } finally {
      setSaving(false);
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
        <input type="number" min={1} value={lines} onChange={(e) => setLines(e.target.value)}
               placeholder={t('hydrology:keylineCoverParcel')}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <div>
        <label className="text-xs text-nkz-muted">{t('hydrology:minLineLength')}</label>
        <input type="number" min={1} value={minLine} onChange={(e) => setMinLine(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 text-sm" />
      </div>
      <button onClick={generate} disabled={loading}
              className="bg-nkz-accent-base text-white px-3 py-1 rounded text-sm w-full">
        {loading ? t('hydrology:loading') : t('hydrology:keypoint')}
      </button>
      {message && <p role="alert" className="text-xs text-nkz-muted">{message}</p>}
      {result?.status === 'ok' && result.coverage_pct != null && (
        <p className="text-xs text-nkz-muted">
          {t('hydrology:keylineCoverage', { pct: Number(result.coverage_pct).toFixed(0) })}
          {result.coverage_truncated ? ` ${t('hydrology:keylineCoverageTruncated')}` : ''}
        </p>
      )}
      {hasLines && (
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
          <ExportMenu designType="keyline" geometry={{ type: 'MultiLineString', coordinates: (keylineGeoms.length ? keylineGeoms : patternGeoms).map((g: any) => g.coordinates) }} designId={savedId} />
        </>
      )}
    </div>
  );
};

export default KeylineDesigner;
