import { i18n } from '@nekazari/sdk';
import en from './locales/en.json';
import es from './locales/es.json';

const NS = 'hydrology';

function register(): void {
  const add = i18n && 'addResourceBundle' in i18n ? i18n.addResourceBundle : undefined;
  if (typeof add !== 'function') return;
  add.call(i18n, 'en', NS, en, true, true);
  add.call(i18n, 'es', NS, es, true, true);
}

register();
