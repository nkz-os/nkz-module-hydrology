/**
 * ExampleSlot — replace with your actual slot component.
 *
 * Slot components render inside host-provided containers, wrapped by the
 * host's NKZProvider. All `@nekazari/module-kit` hooks resolve automatically.
 *
 * Keep panels responsive (300–600px wide).
 */
import React, { useState } from 'react';
import { useAuth, useI18n } from '@nekazari/module-kit';
import { AlertCircle, RefreshCw } from 'lucide-react';

interface ExampleSlotProps {
  className?: string;
}

export const ExampleSlot: React.FC<ExampleSlotProps> = ({ className }) => {
  const { t } = useI18n();
  const { isAuthenticated, user } = useAuth();
  const [loading, setLoading] = useState(false);

  if (!isAuthenticated) {
    return (
      <div className={`flex items-center gap-2 text-amber-600 p-4 ${className ?? ''}`}>
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
        <span className="text-sm">{t('slot.authRequired')}</span>
      </div>
    );
  }

  return (
    <div className={`p-4 space-y-3 ${className ?? ''}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">{t('module.title')}</h3>
        <button
          onClick={() => setLoading((l) => !l)}
          className="p-1 rounded hover:bg-slate-100 text-slate-500"
          aria-label={t('slot.refreshAria')}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="text-xs text-slate-500 space-y-1 bg-slate-50 rounded p-2">
        <div className="flex justify-between gap-2">
          <span>{t('slot.user')}</span>
          <span className="text-slate-700 truncate">{user?.email ?? '—'}</span>
        </div>
      </div>

      <p className="text-xs text-slate-400 italic">{t('slot.placeholder')}</p>
    </div>
  );
};

export default ExampleSlot;
