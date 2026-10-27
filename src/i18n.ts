import { i18n } from '@nekazari/sdk';
import en from './locales/en.json';
import es from './locales/es.json';

const ns = 'hydrology';

// The locale files nest the module's strings under a `hydrology` key, while the
// components read `hydrology:<key>`: the bundle must hold the nested strings at
// its root (plus any top-level keys), or every lookup misses and shows the raw key.
function bundle(locale: Record<string, unknown>): Record<string, unknown> {
  const { hydrology, ...rest } = locale as { hydrology?: Record<string, unknown> };
  return { ...(hydrology ?? {}), ...rest };
}

export function registerI18n(): void {
  if (!i18n || typeof (i18n as any).addResourceBundle !== 'function') return;
  (i18n as any).addResourceBundle('en', ns, bundle(en), true, true);
  (i18n as any).addResourceBundle('es', ns, bundle(es), true, true);
}

registerI18n();
