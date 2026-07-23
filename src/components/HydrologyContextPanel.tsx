import React from 'react';
import { useTranslation } from 'react-i18next';
import { useViewer } from '@nekazari/sdk';
import { api } from '../services/api';
import ZonalKpiTable from './ZonalKpiTable';
import ParcelSummary from './ParcelSummary';
import KeylineDesigner from './KeylineDesigner';
import PondSitingTool from './PondSitingTool';
import SwaleDesigner from './SwaleDesigner';
import CheckDamTool from './CheckDamTool';
import DesignManager from './DesignManager';
import ScenarioPanel from './ScenarioPanel';

type TabId = 'kpis' | 'scenarios' | 'keyline' | 'pond' | 'swale' | 'dam' | 'designs';

const TABS: { id: TabId; labelKey: string }[] = [
  { id: 'kpis', labelKey: 'hydrology:zonalKpis' },
  { id: 'scenarios', labelKey: 'hydrology:scenarios' },
  { id: 'keyline', labelKey: 'hydrology:keylineDesigner' },
  { id: 'pond', labelKey: 'hydrology:pondSiting' },
  { id: 'swale', labelKey: 'hydrology:swaleDesigner' },
  { id: 'dam', labelKey: 'hydrology:checkDam' },
  { id: 'designs', labelKey: 'hydrology:designs' },
];

type AnalysisState = 'idle' | 'running' | 'done' | 'failed';

const POLL_INTERVAL_MS = 5000;
const POLL_MAX_MS = 10 * 60 * 1000; // ~10 min cap

const HydrologyContextPanel: React.FC = () => {
  const { t } = useTranslation();
  const { selectedEntityId: parcelId } = useViewer();
  const [activeTab, setActiveTab] = React.useState<TabId>('kpis');
  const [analysis, setAnalysis] = React.useState<AnalysisState>('idle');
  const [refreshKey, setRefreshKey] = React.useState(0);
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const deadlineRef = React.useRef<number>(0);

  const stopPolling = React.useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Reset analysis state when the selected parcel changes; also clear on unmount.
  React.useEffect(() => {
    stopPolling();
    setAnalysis('idle');
    return stopPolling;
  }, [parcelId, stopPolling]);

  const runAnalysis = React.useCallback(async () => {
    if (!parcelId) return;
    stopPolling();
    setAnalysis('running');
    try {
      const { job_id } = await api.analyzeParcel(parcelId);
      deadlineRef.current = Date.now() + POLL_MAX_MS;
      pollRef.current = setInterval(async () => {
        if (Date.now() > deadlineRef.current) {
          stopPolling();
          setAnalysis('failed');
          return;
        }
        try {
          const job = await api.getJob(job_id);
          if (job.status === 'finished') {
            stopPolling();
            setAnalysis('done');
            setRefreshKey((k) => k + 1);
          } else if (job.status === 'failed') {
            stopPolling();
            setAnalysis('failed');
          }
        } catch {
          stopPolling();
          setAnalysis('failed');
        }
      }, POLL_INTERVAL_MS);
    } catch {
      setAnalysis('failed');
    }
  }, [parcelId, stopPolling]);

  if (!parcelId) {
    return (
      <div className="p-4">
        <h3 className="text-sm font-semibold text-nkz-text mb-1">{t('hydrology:title')}</h3>
        <p className="text-xs text-nkz-muted">{t('hydrology:noData')}</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-2 gap-2">
        <h3 className="text-sm font-semibold text-nkz-text">{t('hydrology:title')}</h3>
        <button
          className="text-xs bg-nkz-accent text-white px-2 py-1 rounded whitespace-nowrap disabled:opacity-60"
          onClick={runAnalysis}
          disabled={analysis === 'running'}
        >
          {analysis === 'running' ? t('hydrology:analysisRunning') : t('hydrology:runAnalysisCta')}
        </button>
      </div>
      {analysis === 'done' && <p className="text-xs text-nkz-accent mb-2">{t('hydrology:analysisDone')}</p>}
      {analysis === 'failed' && <p className="text-xs text-red-500 mb-2">{t('hydrology:analysisFailed')}</p>}
      <div className="flex gap-1 mb-3 border-b border-nkz-border overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`px-2 py-1 text-xs border-b-2 whitespace-nowrap ${
              activeTab === tab.id ? 'border-nkz-accent text-nkz-accent' : 'border-transparent text-nkz-muted'
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>
      {activeTab === 'kpis' && (
        <>
          <ParcelSummary parcelId={parcelId} refreshKey={refreshKey} />
          <ZonalKpiTable
            key={refreshKey}
            parcelId={parcelId}
            onRunAnalysis={runAnalysis}
            analysisRunning={analysis === 'running'}
          />
        </>
      )}
      {activeTab === 'scenarios' && <ScenarioPanel parcelId={parcelId} refreshKey={refreshKey} />}
      {activeTab === 'keyline' && <KeylineDesigner parcelId={parcelId} />}
      {activeTab === 'pond' && <PondSitingTool parcelId={parcelId} />}
      {activeTab === 'swale' && <SwaleDesigner parcelId={parcelId} />}
      {activeTab === 'dam' && <CheckDamTool parcelId={parcelId} />}
      {activeTab === 'designs' && <DesignManager key={refreshKey} parcelId={parcelId} />}
    </div>
  );
};

export default HydrologyContextPanel;
