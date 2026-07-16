import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type DesignEntity, type ExportEnvelope } from '../services/api';
import { useHydrologyLayerContext } from '../services/layerContext';
import type { DesignGeometry } from '../services/layerStore';

interface Props { parcelId: string; }

type Format = 'gpx' | 'kml' | 'geojson';

function triggerDownload(content: string, mediaType: string, filename: string): void {
  const blob = new Blob([content], { type: mediaType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const DesignManager: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation();
  const { setDesigns, setDesignsVisible } = useHydrologyLayerContext();
  const [designs, setList] = useState<DesignEntity[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listDesigns(parcelId);
      setList(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error('Failed to list designs:', e);
      setList([]);
    } finally {
      setLoading(false);
    }
  }, [parcelId]);

  useEffect(() => { load(); }, [load]);

  const showOnMap = (d: DesignEntity) => {
    const geometry = d['location']?.value;
    if (!geometry) return;
    const params = d['nkz:parameters']?.value as { radius?: number } | undefined;
    const geom: DesignGeometry = {
      id: d.id,
      type: (d['nkz:designType']?.value as DesignGeometry['type']) || 'keyline',
      geometry,
      label: d['nkz:label']?.value,
      radius: params?.radius,
    };
    setDesigns([geom]);
    setDesignsVisible(true);
  };

  const exportDesign = async (d: DesignEntity, format: Format) => {
    try {
      const res = await api.exportDesign(d.id, format);
      const name = d['nkz:label']?.value || 'design';
      if (format === 'geojson') {
        triggerDownload(JSON.stringify(res), 'application/geo+json', `${name}.geojson`);
      } else {
        const env = res as ExportEnvelope;
        triggerDownload(env.content, env.mediaType, env.filename);
      }
    } catch (e) {
      console.error('Export failed:', e);
    }
  };

  const remove = async (d: DesignEntity) => {
    if (!window.confirm(t('hydrology:confirmDelete'))) return;
    try {
      await api.deleteDesign(d.id);
      setList((prev) => prev.filter((x) => x.id !== d.id));
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  if (loading) {
    return <p className="text-xs text-nkz-muted">{t('hydrology:loading')}</p>;
  }
  if (!designs.length) {
    return <p className="text-xs text-nkz-muted">{t('hydrology:noDesigns')}</p>;
  }

  return (
    <div className="space-y-2">
      {designs.map((d) => (
        <div key={d.id} className="border border-nkz-border rounded p-2 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-nkz-text truncate">
              {d['nkz:label']?.value || t('hydrology:untitledDesign')}
            </span>
            <span className="text-xs text-nkz-muted whitespace-nowrap">
              {d['nkz:designType']?.value}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            <button onClick={() => showOnMap(d)}
                    className="text-xs bg-nkz-accent text-white px-2 py-1 rounded">
              {t('hydrology:showOnMap')}
            </button>
            <button onClick={() => exportDesign(d, 'gpx')}
                    className="text-xs border px-2 py-1 rounded">{t('hydrology:downloadGpx')}</button>
            <button onClick={() => exportDesign(d, 'kml')}
                    className="text-xs border px-2 py-1 rounded">{t('hydrology:downloadKml')}</button>
            <button onClick={() => exportDesign(d, 'geojson')}
                    className="text-xs border px-2 py-1 rounded">{t('hydrology:downloadGeoJson')}</button>
            <button onClick={() => remove(d)}
                    className="text-xs border border-red-400 text-red-500 px-2 py-1 rounded">
              {t('hydrology:delete')}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};

export default DesignManager;
