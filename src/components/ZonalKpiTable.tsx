import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, ZoneKpi } from '../services/api';

interface Props {
  parcelId: string;
  onRunAnalysis?: () => void;
  analysisRunning?: boolean;
}

const ZonalKpiTable: React.FC<Props> = ({ parcelId, onRunAnalysis, analysisRunning }) => {
  const { t } = useTranslation();
  const [zones, setZones] = useState<ZoneKpi[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) { setLoading(false); return; }
    setLoading(true);
    api.getZones(parcelId).then(setZones).catch(() => setZones([])).finally(() => setLoading(false));
  }, [parcelId]);

  if (loading) return <p className="text-nkz-muted text-sm">{t('hydrology:loading')}</p>;
  if (!zones.length) return (
    <div className="text-sm">
      <p className="text-nkz-muted mb-2">{t('hydrology:noData')}</p>
      {onRunAnalysis && (
        <button
          className="text-xs bg-nkz-accent text-white px-2 py-1 rounded whitespace-nowrap disabled:opacity-60"
          onClick={onRunAnalysis}
          disabled={analysisRunning}
        >
          {analysisRunning ? t('hydrology:analysisRunning') : t('hydrology:runAnalysisCta')}
        </button>
      )}
    </div>
  );

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-nkz-muted">
          <th className="text-left">{t('hydrology:zone')}</th>
          <th className="text-right">{t('hydrology:runoff')}</th>
          <th className="text-right">{t('hydrology:peakFlow')}</th>
          <th className="text-right">{t('hydrology:sediment')}</th>
          <th className="text-right">{t('hydrology:saturation')}</th>
          <th className="text-right">{t('hydrology:pondViability')}</th>
        </tr>
      </thead>
      <tbody>
        {zones.map((z) => (
          <tr key={z.id} className="border-t border-nkz-border">
            <td>{z.zoneId}</td>
            <td className="text-right">{z.runoffMm?.toFixed(1) ?? '-'}</td>
            <td className="text-right">{z.peakFlowM3s?.toFixed(2) ?? '-'}</td>
            <td className="text-right">{z.sedimentYieldTonnes?.toFixed(2) ?? '-'}</td>
            <td className="text-right">{z.soilSaturationPct?.toFixed(0) ?? '-'}%</td>
            <td className="text-right">{z.pondViability?.toFixed(2) ?? '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

export default ZonalKpiTable;
