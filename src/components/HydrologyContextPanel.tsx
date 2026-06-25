import React from 'react';
import { useTranslation } from 'react-i18next';
import { useViewer } from '@nekazari/sdk';
import ZonalKpiTable from './ZonalKpiTable';
import KeylineDesigner from './KeylineDesigner';
import PondSitingTool from './PondSitingTool';
import SwaleDesigner from './SwaleDesigner';
import CheckDamTool from './CheckDamTool';

type TabId = 'kpis' | 'keyline' | 'pond' | 'swale' | 'dam';

const TABS: { id: TabId; labelKey: string }[] = [
  { id: 'kpis', labelKey: 'hydrology:zonalKpis' },
  { id: 'keyline', labelKey: 'hydrology:keylineDesigner' },
  { id: 'pond', labelKey: 'hydrology:pondSiting' },
  { id: 'swale', labelKey: 'hydrology:swaleDesigner' },
  { id: 'dam', labelKey: 'hydrology:checkDam' },
];

const HydrologyContextPanel: React.FC = () => {
  const { t } = useTranslation();
  const { selectedEntityId: parcelId } = useViewer();
  const [activeTab, setActiveTab] = React.useState<TabId>('kpis');

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
      <h3 className="text-sm font-semibold text-nkz-text mb-2">{t('hydrology:title')}</h3>
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
      {activeTab === 'kpis' && <ZonalKpiTable parcelId={parcelId} />}
      {activeTab === 'keyline' && <KeylineDesigner parcelId={parcelId} />}
      {activeTab === 'pond' && <PondSitingTool parcelId={parcelId} />}
      {activeTab === 'swale' && <SwaleDesigner parcelId={parcelId} />}
      {activeTab === 'dam' && <CheckDamTool parcelId={parcelId} />}
    </div>
  );
};

export default HydrologyContextPanel;
