import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, ScenarioComparison } from '../services/api';

interface Props {
  parcelId: string;
  refreshKey?: number;
}

/**
 * Baseline vs intervention scenario comparison (Phase 1.2). Computed on demand
 * from the latest hydrology record + the parcel's current capture designs, so it
 * always reflects the latest designs (re-run DEM analysis to refresh inputs).
 */
const ScenarioPanel: React.FC<Props> = ({ parcelId, refreshKey }) => {
  const { t } = useTranslation();
  const [data, setData] = useState<ScenarioComparison | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .getScenarios(parcelId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [parcelId, refreshKey]);

  if (loading) return <p className="text-nkz-muted text-sm">{t('hydrology:loading')}</p>;
  if (!data || data.status === 'no_data' || !data.intervention || !data.baseline) {
    return <p className="text-nkz-muted text-sm">{t('hydrology:scenarioNoData')}</p>;
  }

  const b = data.baseline;
  const iv = data.intervention;
  const rows: { key: string; baseline: number; intervention: number; digits: number; suffix?: string }[] = [
    { key: 'scenarioCaptured', baseline: b.water_captured_m3, intervention: iv.water_captured_m3, digits: 0 },
    { key: 'scenarioSediment', baseline: b.sediment_retained_t, intervention: iv.sediment_retained_t, digits: 2 },
    { key: 'scenarioEarthwork', baseline: b.earthwork_m3, intervention: iv.earthwork_m3, digits: 0 },
    { key: 'scenarioInvestment', baseline: b.investment_eur, intervention: iv.investment_eur, digits: 0 },
    { key: 'scenarioAutonomy', baseline: b.water_autonomy_pct, intervention: iv.water_autonomy_pct, digits: 0, suffix: '%' },
  ];
  const fmt = (v: number, d: number, s = '') => (v == null ? '-' : `${v.toFixed(d)}${s}`);

  return (
    <div className="text-xs">
      <table className="w-full">
        <thead>
          <tr className="text-nkz-muted">
            <th className="text-left font-normal">{t('hydrology:scenarioMetric')}</th>
            <th className="text-right font-normal">{t('hydrology:scenarioBaseline')}</th>
            <th className="text-right font-normal">{t('hydrology:scenarioIntervention')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-nkz-border">
              <td className="py-0.5">{t(`hydrology:${r.key}`)}</td>
              <td className="text-right">{fmt(r.baseline, r.digits, r.suffix)}</td>
              <td className="text-right text-nkz-accent font-medium">{fmt(r.intervention, r.digits, r.suffix)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-nkz-muted mt-2">
        {t('hydrology:scenarioDesigns', { count: data.designsConsidered ?? 0 })}
      </p>
      {data.assumptions && <p className="text-[10px] text-nkz-muted mt-1 italic">{data.assumptions}</p>}
    </div>
  );
};

export default ScenarioPanel;
