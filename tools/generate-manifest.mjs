import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(resolve(__dirname, '../package.json'), 'utf-8'));
const mfManifest = JSON.parse(readFileSync(resolve(__dirname, '../dist/mf-manifest.json'), 'utf-8'));

const manifest = {
  id: pkg.nkz?.moduleId || 'hydrology',
  name: pkg.name,
  version: pkg.version,
  description: pkg.description,
  license: pkg.license,
  hostApiVersion: '^2.0.0',
  remoteEntry: 'remoteEntry.js',
  mfManifest: 'mf-manifest.json',
  shared: (mfManifest.shared || []).map((s) => ({ name: s.name, version: s.version })),
  exposes: mfManifest.exposes,
  buildInfo: mfManifest.metaData?.buildInfo,
  generatedAt: new Date().toISOString(),
};

writeFileSync(resolve(__dirname, '../dist/manifest.json'), JSON.stringify(manifest, null, 2));
console.log('dist/manifest.json generated');
