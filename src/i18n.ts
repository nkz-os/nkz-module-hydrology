import { i18n } from '@nekazari/sdk';
import en from './locales/en.json';
import es from './locales/es.json';

const ns = 'hydrology';

export function registerI18n(): void {
  if (!i18n || typeof (i18n as any).addResourceBundle !== 'function') return;
  (i18n as any).addResourceBundle('en', ns, en, true, true);
  (i18n as any).addResourceBundle('es', ns, es, true, true);
}

registerI18n();
