/**
 * Dev-only entry point. Used by `pnpm run dev` (Vite dev server) to render
 * the module standalone with a MockProvider for all SDK hooks. In production
 * the host loads dist/nkz-module.js (IIFE) directly and provides the real
 * NKZProvider — this file is not part of the production bundle.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { MockProvider } from '@nekazari/module-kit/mock';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MockProvider fixtures={{ moduleId: 'hydrology' }}>
      <App />
    </MockProvider>
  </React.StrictMode>,
);
