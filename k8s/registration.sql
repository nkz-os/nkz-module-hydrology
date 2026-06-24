-- =============================================================================
-- NKZ Water Studio — Marketplace Registration
-- =============================================================================
-- Execute:
--   PGPOD=$(kubectl get pods -n nekazari -l app=postgresql -o jsonpath='{.items[0].metadata.name}')
--   kubectl exec -it -n nekazari $PGPOD -- psql -U nekazari -d nekazari -f -
-- =============================================================================

INSERT INTO marketplace_modules (
    id, name, display_name, description,
    remote_entry_url, version, author, category,
    route_path, label, module_type, required_plan_type,
    pricing_tier, is_local, is_active, required_roles,
    metadata
) VALUES (
    'hydrology', 'hydrology', 'NKZ Water Studio',
    'NKZ Water Studio — DEM watershed & flow analysis (beta). Hydrological modeling capabilities in active development.',
    '/modules/hydrology/nkz-module.js', '0.0.1-beta', 'nkz-os', 'hydrology',
    '/hydrology', 'NKZ Water Studio', 'ADDON_FREE', 'basic',
    'FREE', false, true,
    ARRAY['Farmer', 'TenantAdmin', 'PlatformAdmin'],
    '{
        "icon": "💧",
        "color": "#06B6D4",
        "shortDescription": "DEM watershed & flow analysis (beta)",
        "features": [
            "DEM-based watershed delineation (beta)",
            "Stream network extraction"
        ],
        "maturity": "beta",
        "setup_parcel_url": "http://hydrology-api-service:8000/api/v1/hydrology/internal/setup-parcel",
        "backend_url": "http://hydrology-api-service:8000",
        "backend_only": false,
        "navigationItems": [
            {
                "path": "/hydrology",
                "label": "Water Studio",
                "icon": "droplets"
            }
        ]
    }'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name      = EXCLUDED.display_name,
    description       = EXCLUDED.description,
    version           = EXCLUDED.version,
    remote_entry_url  = EXCLUDED.remote_entry_url,
    is_active         = true,
    metadata          = EXCLUDED.metadata,
    updated_at        = NOW();
