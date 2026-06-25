import React from 'react';
import { useTranslation } from 'react-i18next';
import { exportToGisRouting } from '../services/gisRoutingClient';
import { api } from '../services/api';

interface Props {
  designType: string;
  geometry: Record<string, unknown>;
  designId?: string;
}

const ExportMenu: React.FC<Props> = ({ designType, geometry, designId }) => {
  const { t } = useTranslation();

  const copyGeoJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(geometry));
  };

  const download = (format: string) => {
    if (designId) {
      window.open(api.getExportUrl(designId, format as any), '_blank');
    } else {
      const blob = new Blob([JSON.stringify(geometry)], { type: 'application/geo+json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${designType}.${format}`; a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <div className="flex flex-wrap gap-1 mt-2">
      <button onClick={() => exportToGisRouting(geometry)}
              className="text-xs bg-nkz-accent text-white px-2 py-1 rounded">
        {t('hydrology:exportGisRouting')}
      </button>
      <button onClick={copyGeoJSON}
              className="text-xs border px-2 py-1 rounded">
        {t('hydrology:copyGeoJson')}
      </button>
      <button onClick={() => download('gpx')}
              className="text-xs border px-2 py-1 rounded">
        {t('hydrology:downloadGpx')}
      </button>
    </div>
  );
};

export default ExportMenu;
