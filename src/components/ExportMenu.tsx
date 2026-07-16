import React from 'react';
import { useTranslation } from 'react-i18next';
import { exportToGisRouting } from '../services/gisRoutingClient';
import { api, type ExportEnvelope } from '../services/api';

interface Props {
  designType: string;
  geometry: Record<string, unknown>;
  designId?: string;
}

function triggerDownload(content: string, mediaType: string, filename: string): void {
  const blob = new Blob([content], { type: mediaType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const ExportMenu: React.FC<Props> = ({ designType, geometry, designId }) => {
  const { t } = useTranslation();

  const copyGeoJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(geometry));
  };

  // Persisted design: fetch the gateway-safe envelope and build honest files.
  const download = async (format: 'gpx' | 'kml' | 'geojson') => {
    if (!designId) return;
    const res = await api.exportDesign(designId, format);
    if (format === 'geojson') {
      triggerDownload(
        JSON.stringify(res),
        'application/geo+json',
        `${designType}.geojson`,
      );
    } else {
      const env = res as ExportEnvelope;
      triggerDownload(env.content, env.mediaType, env.filename);
    }
  };

  // Unsaved design: only a truthful local GeoJSON path (no fake .gpx blob).
  const downloadLocalGeoJSON = () => {
    triggerDownload(JSON.stringify(geometry), 'application/geo+json', `${designType}.geojson`);
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
      {designId ? (
        <>
          <button onClick={() => download('gpx')}
                  className="text-xs border px-2 py-1 rounded">
            {t('hydrology:downloadGpx')}
          </button>
          <button onClick={() => download('kml')}
                  className="text-xs border px-2 py-1 rounded">
            {t('hydrology:downloadKml')}
          </button>
          <button onClick={() => download('geojson')}
                  className="text-xs border px-2 py-1 rounded">
            {t('hydrology:downloadGeoJson')}
          </button>
        </>
      ) : (
        <button onClick={downloadLocalGeoJSON}
                className="text-xs border px-2 py-1 rounded">
          {t('hydrology:downloadGeoJson')}
        </button>
      )}
    </div>
  );
};

export default ExportMenu;
