import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, AlertResult } from '../services/api';

interface Props {
  parcelId: string;
  refreshKey?: number;
}

const SEV_COLOR: Record<string, string> = {
  critical: 'text-red-500',
  warning: 'text-amber-500',
  info: 'text-nkz-accent',
};

/**
 * Active hydrologic alerts (Phase 2A — reactive). Evaluated on demand from the
 * latest record: saturation-excess (Dunne) and infiltration-excess (Hortonian)
 * runoff risk. Refreshes on DEM analysis (re-run to update inputs).
 */
const AlertPanel: React.FC<Props> = ({ parcelId, refreshKey }) => {
  const { t } = useTranslation();
  const [data, setData] = useState<AlertResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .getAlerts(parcelId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [parcelId, refreshKey]);

  if (loading) return <p className="text-nkz-muted text-sm">{t('hydrology:loading')}</p>;
  if (!data || data.status === 'no_data') {
    return <p className="text-nkz-muted text-sm">{t('hydrology:alertNoData')}</p>;
  }

  const alerts = data.alerts || [];
  if (!alerts.length) {
    return <p className="text-green-600 text-sm">{t('hydrology:noAlerts')}</p>;
  }

  return (
    <div className="space-y-2">
      {alerts.map((a, i) => (
        <div key={i} className="border border-nkz-border rounded p-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-medium ${SEV_COLOR[a.severity] || 'text-nkz-muted'}`}>
              {t(`hydrology:severity_${a.severity}`, a.severity)}
            </span>
            <span className="text-[10px] text-nkz-muted">
              {t(`hydrology:mechanism_${a.mechanism}`, a.mechanism)}
            </span>
          </div>
          <p className="text-xs mt-1 text-nkz-text">{a.description}</p>
        </div>
      ))}
      {data.inputs && (
        <p className="text-[10px] text-nkz-muted">
          {t('hydrology:alertInputs', {
            sat: data.inputs.soilSaturationPct,
            precip: data.inputs.precipitationMm,
          })}
        </p>
      )}
    </div>
  );
};

export default AlertPanel;
