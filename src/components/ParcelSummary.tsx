import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, ParcelSummary as ParcelSummaryData, DataFidelity } from '../services/api';

interface Props {
  parcelId: string;
  refreshKey?: number;
}

// Tailwind classes per dataFidelity level (brief: ign_5m green / ign_25m cyan /
// degraded_flat amber / unavailable red).
const FIDELITY_STYLES: Record<string, string> = {
  ign_5m: 'bg-green-500/15 text-green-500',
  ign_25m: 'bg-cyan-500/15 text-cyan-500',
  degraded_flat: 'bg-amber-500/15 text-amber-500',
  unavailable: 'bg-red-500/15 text-red-500',
};

function fidelityClass(f?: DataFidelity | null): string {
  return (f && FIDELITY_STYLES[f]) || 'bg-nkz-border text-nkz-muted';
}

function fmt(v: number | undefined, digits: number, suffix = ''): string {
  return v == null ? '-' : `${v.toFixed(digits)}${suffix}`;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

const ParcelSummary: React.FC<Props> = ({ parcelId, refreshKey }) => {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<ParcelSummaryData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) { setLoading(false); return; }
    setLoading(true);
    api.getSummary(parcelId)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [parcelId, refreshKey]);

  // Empty/no_data: render nothing extra — the run-analysis CTA already lives in
  // the panel header + ZonalKpiTable below, so we must not duplicate it.
  if (loading || !summary || summary.status === 'no_data') return null;

  const k = summary.kpis || {};
  const fidelity = summary.dataFidelity;
  const cells: { labelKey: string; value: string }[] = [
    { labelKey: 'hydrology:runoff', value: fmt(k.runoffMm, 1) },
    { labelKey: 'hydrology:peakFlow', value: fmt(k.peakFlowM3s, 2) },
    { labelKey: 'hydrology:sediment', value: fmt(k.sedimentYieldTonnes, 2) },
    { labelKey: 'hydrology:saturation', value: fmt(k.soilSaturationPct, 0, '%') },
    { labelKey: 'hydrology:twiMeanKpi', value: fmt(k.twiMean, 1) },
    { labelKey: 'hydrology:streamLength', value: fmt(k.streamLengthM, 0) },
  ];
  const meteo: { labelKey: string; value: string }[] = [
    { labelKey: 'hydrology:eto', value: fmt(k.etoMm, 1) },
    { labelKey: 'hydrology:precipitation', value: fmt(k.precipitationMm, 1) },
    { labelKey: 'hydrology:temperature', value: fmt(k.temperatureAvg, 1) },
  ];
  const hasMeteo = k.etoMm != null || k.precipitationMm != null || k.temperatureAvg != null;

  const sources: string[] = [];
  if (summary.soilSource) sources.push(`${t('hydrology:soilSource')}: ${summary.soilSource}`);
  if (summary.vegetationSource) sources.push(`${t('hydrology:vegetationSource')}: ${summary.vegetationSource}`);

  return (
    <div className="mb-3 pb-3 border-b border-nkz-border">
      <div className="flex items-center justify-between mb-2 gap-2">
        <h4 className="text-xs font-semibold text-nkz-text">{t('hydrology:summaryTitle')}</h4>
        {fidelity && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${fidelityClass(fidelity)}`}>
            {t(`hydrology:fidelity_${fidelity}`, fidelity)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 mb-2">
        {cells.map((c) => (
          <div key={c.labelKey}>
            <div className="text-[10px] text-nkz-muted">{t(c.labelKey)}</div>
            <div className="text-sm font-semibold text-nkz-text">{c.value}</div>
          </div>
        ))}
      </div>
      {hasMeteo && (
        <div className="grid grid-cols-3 gap-2 mb-2">
          {meteo.map((c) => (
            <div key={c.labelKey}>
              <div className="text-[10px] text-nkz-muted">{t(c.labelKey)}</div>
              <div className="text-sm font-semibold text-nkz-text">{c.value}</div>
            </div>
          ))}
        </div>
      )}
      {(sources.length > 0 || summary.observedAt) && (
        <div className="text-[10px] text-nkz-muted">
          {sources.join(' · ')}
          {sources.length > 0 && summary.observedAt ? ' · ' : ''}
          {summary.observedAt ? `${t('hydrology:observedAt')}: ${fmtDate(summary.observedAt)}` : ''}
        </div>
      )}
    </div>
  );
};

export default ParcelSummary;
