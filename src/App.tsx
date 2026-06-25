/**
 * NKZ Water Studio — Module landing page.
 *
 * Shown at /hydrology. The real work happens in the 3D viewer via slots
 * (context-panel + map-layer). This page explains the module and provides
 * a quick entry point to the viewer.
 */
import './i18n';
import React from 'react';
import { useAuth } from '@nekazari/module-kit';
import { useTranslation } from 'react-i18next';
import './index.css';

const App: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const { t } = useTranslation();

  return (
    <div className="w-full min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-gradient-to-r from-cyan-600 to-blue-600 text-white py-12 px-6">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-3xl font-bold mb-2">{t('hydrology:title', 'NKZ Water Studio')}</h1>
          <p className="text-cyan-100 text-lg">
            {t('hydrology:subtitle', 'Watershed analysis and hydrological design tools for precision agriculture.')}
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-3xl mx-auto py-8 px-6 space-y-8">
        {/* How it works */}
        <section>
          <h2 className="text-xl font-semibold text-gray-800 mb-3">
            {t('hydrology:howItWorks', 'How it works')}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              {
                step: '1',
                title: t('hydrology:step1Title', 'Select a parcel'),
                desc: t('hydrology:step1Desc', 'Open the 3D viewer and click on any AgriParcel to activate the hydrology tools.'),
              },
              {
                step: '2',
                title: t('hydrology:step2Title', 'Run DEM analysis'),
                desc: t('hydrology:step2Desc', 'The system downloads high-res elevation data and computes watershed, slope and TWI rasters.'),
              },
              {
                step: '3',
                title: t('hydrology:step3Title', 'Design & export'),
                desc: t('hydrology:step3Desc', 'Use the design tools to place keylines, ponds, swales and check dams. Export to GIS-routing, GPX or KML.'),
              },
            ].map((item) => (
              <div key={item.step} className="bg-white rounded-lg shadow p-4">
                <div className="text-cyan-600 font-bold text-lg mb-1">{item.step}</div>
                <h3 className="font-medium text-gray-800 mb-1">{item.title}</h3>
                <p className="text-sm text-gray-500">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Tools overview */}
        <section>
          <h2 className="text-xl font-semibold text-gray-800 mb-3">
            {t('hydrology:tools', 'Design tools')}
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { icon: '🔑', label: t('hydrology:toolKeyline', 'Keyline') },
              { icon: '💧', label: t('hydrology:toolPond', 'Pond') },
              { icon: '🏗️', label: t('hydrology:toolSwale', 'Infiltration swale') },
              { icon: '🪨', label: t('hydrology:toolDam', 'Check dam') },
            ].map((tool) => (
              <div key={tool.label} className="bg-white rounded-lg shadow p-3 text-center">
                <div className="text-2xl mb-1">{tool.icon}</div>
                <div className="text-xs text-gray-600">{tool.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <div className="bg-cyan-50 border border-cyan-200 rounded-lg p-6 text-center">
          <p className="text-gray-700 mb-4">
            {t('hydrology:ctaText', 'All design tools are available in the 3D viewer when a parcel is selected.')}
          </p>
          {isAuthenticated ? (
            <a
              href="/viewer"
              className="inline-block bg-cyan-600 hover:bg-cyan-700 text-white font-medium py-2 px-6 rounded-lg transition"
            >
              {t('hydrology:openViewer', 'Open 3D Viewer')}
            </a>
          ) : (
            <p className="text-sm text-gray-500">{t('hydrology:notAuthenticated', 'Sign in to access the viewer.')}</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default App;
