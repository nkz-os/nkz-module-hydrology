import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@nekazari/sdk';
import { api, ApiError, CalculationMode, DesignInfo, ParcelSettings, ReturnPeriod } from '../services/api';

const WRITE_ROLES = ['TechnicalConsultant', 'TenantAdmin', 'PlatformAdmin'];
const RETURN_PERIODS: ReturnPeriod[] = [10, 25, 100];
const MODES: CalculationMode[] = ['storm', 'retention'];

interface Props {
  parcelId: string;
  onRerun?: () => void;
  analysisRunning?: boolean;
}

/** Mode and return period of a parcel; editable by technicians and admins only. */
const CalculationModeControl: React.FC<Props> = ({ parcelId, onRerun, analysisRunning }) => {
  const { t } = useTranslation();
  const { hasAnyRole } = useAuth();
  const canEdit = hasAnyRole(WRITE_ROLES);
  const [settings, setSettings] = useState<ParcelSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<'load' | 'forbidden' | 'invalid' | 'save' | null>(null);
  const [offerRerun, setOfferRerun] = useState(false);

  useEffect(() => {
    setSettings(null);
    setOfferRerun(false);
    setError(null);
    if (!parcelId) return;
    let live = true;
    api.getSettings(parcelId).then((s) => live && setSettings(s)).catch(() => live && setError('load'));
    return () => { live = false; };
  }, [parcelId]);

  const save = useCallback(async (mode: CalculationMode, period: ReturnPeriod) => {
    setSaving(true);
    setError(null);
    try {
      setSettings(await api.putSettings(parcelId, mode, period));
      setOfferRerun(true);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setError(status === 403 ? 'forbidden' : status === 422 ? 'invalid' : 'save');
    } finally {
      setSaving(false);
    }
  }, [parcelId]);

  if (!settings && error !== 'load') return null;
  // GET failed: show the defaults (marked as such) next to the error.
  const shown: ParcelSettings = settings ?? { mode: 'storm', return_period_years: 10, is_default: true };

  const disabled = !canEdit || saving;
  const errorKey = {
    load: 'modeLoadFailed', forbidden: 'modeForbidden', invalid: 'modeInvalid', save: 'modeSaveFailed',
  };
  return (
    <div className="mb-3 pb-3 border-b border-nkz-border text-xs">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-semibold text-nkz-text-primary">{t('hydrology:modeTitle')}</span>
        {shown.is_default && <span className="text-[10px] text-nkz-muted">{t('hydrology:modeDefault')}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="bg-nkz-surface border border-nkz-border rounded px-1 py-0.5 text-nkz-text-primary disabled:opacity-60"
          aria-label={t('hydrology:modeTitle')}
          value={shown.mode}
          disabled={disabled}
          onChange={(e) => save(e.target.value as CalculationMode, shown.return_period_years)}
        >
          {MODES.map((m) => (
            <option key={m} value={m}>{t(m === 'storm' ? 'hydrology:modeStorm' : 'hydrology:modeRetention')}</option>
          ))}
        </select>
        {shown.mode === 'storm' && (
          <select
            className="bg-nkz-surface border border-nkz-border rounded px-1 py-0.5 text-nkz-text-primary disabled:opacity-60"
            aria-label={t('hydrology:returnPeriod')}
            value={shown.return_period_years}
            disabled={disabled}
            onChange={(e) => save(shown.mode, Number(e.target.value) as ReturnPeriod)}
          >
            {RETURN_PERIODS.map((p) => (
              <option key={p} value={p}>{t('hydrology:returnPeriodYears', { years: p })}</option>
            ))}
          </select>
        )}
        {saving && <span className="text-nkz-muted">{t('hydrology:modeSaving')}</span>}
      </div>
      {!canEdit && <p className="text-[10px] text-nkz-muted mt-1">{t('hydrology:modeReadOnly')}</p>}
      {error && <p className="text-nkz-danger mt-1">{t(`hydrology:${errorKey[error]}`)}</p>}
      {offerRerun && onRerun && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-nkz-text-primary">{t('hydrology:modeRerunOffer')}</span>
          <button
            className="text-xs bg-nkz-accent-base text-white px-2 py-1 rounded whitespace-nowrap disabled:opacity-60"
            disabled={analysisRunning}
            onClick={() => { setOfferRerun(false); onRerun(); }}
          >
            {analysisRunning ? t('hydrology:analysisRunning') : t('hydrology:modeRerun')}
          </button>
          <button className="text-xs text-nkz-muted" onClick={() => setOfferRerun(false)}>
            {t('hydrology:modeRerunDismiss')}
          </button>
        </div>
      )}
    </div>
  );
};

/** One line stating the mode, design depth and source behind a table, plus any caveat. */
export const DesignLabel: React.FC<{ design?: DesignInfo }> = ({ design }) => {
  const { t } = useTranslation();
  if (!design || !design.calculationMode) return null;
  const modeName = t(design.calculationMode === 'storm' ? 'hydrology:modeStorm' : 'hydrology:modeRetention');
  if (design.designRainStatus === 'not_available') {
    return (
      <div className="text-[10px] text-nkz-warning-strong mb-2">
        <span className="font-medium">{modeName}. </span>
        {design.designRainReason
          ? t('hydrology:designNotAvailable', { reason: design.designRainReason })
          : t('hydrology:designNotAvailableNoReason')}
      </div>
    );
  }
  const rawSource = (design.designRainSource ?? '').split(';')[0].trim();
  const source = rawSource === 'reanalysis' ? t('hydrology:designSourceReanalysis') : rawSource;
  return (
    <div className="text-[10px] text-nkz-muted mb-2">
      {design.calculationMode === 'storm' && design.designRainMm != null && design.returnPeriodYears != null
        ? t('hydrology:designStorm', {
            years: design.returnPeriodYears,
            mm: Math.round(design.designRainMm),
            source,
          })
        : `${modeName}: ${t('hydrology:designTypicalYear')}`}
      {design.designRainLowConfidence && (
        <div className="text-nkz-warning-strong">
          {t('hydrology:designLowConfidence', {
            low: design.designRainCiLowMm != null ? Math.round(design.designRainCiLowMm) : '-',
            high: design.designRainCiHighMm != null ? Math.round(design.designRainCiHighMm) : '-',
          })}
        </div>
      )}
    </div>
  );
};

export default CalculationModeControl;
