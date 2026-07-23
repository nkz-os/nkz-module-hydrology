-- =============================================================================
-- NKZ Water Studio — Marketplace Registration
-- =============================================================================
-- Execute:
--   PGPOD=$(kubectl get pods -n nekazari -l app=postgresql -o jsonpath='{.items[0].metadata.name}')
--   kubectl exec -it -n nekazari $PGPOD -- psql -U nekazari -d nekazari -f -
-- =============================================================================
-- Schema-aligned with marketplace_modules (see \d marketplace_modules).
-- NOTE: MF2 remote entry is mf-manifest.json, not a hand-written JS file.
-- =============================================================================

INSERT INTO marketplace_modules (
    id, name, display_name, description,
    remote_entry_url, version, author, category,
    route_path, label, is_local, is_active,
    required_roles, required_plan_level,
    metadata
) VALUES (
    'hydrology', 'hydrology', 'NKZ Water Studio',
    'NKZ Water Studio — DEM analysis, hydrological modeling, water-harvesting design, scenario comparison, compliance checking and runoff-risk alerts for agricultural parcels.',
    '/modules/hydrology/mf-manifest.json', '1.0.0', 'nkz-os', 'hydrology',
    '/hydrology', 'NKZ Water Studio', false, true,
    ARRAY['Farmer', 'TenantAdmin', 'PlatformAdmin'],
    0,
    '{
        "icon": "droplets",
        "color": "#06B6D4",
        "maturity": "beta",
        "shortDescription": "Hydrology, water-harvesting design & compliance",
        "features": [
            "DEM cascade (eu-elevation) + TWI overlay",
            "Flow direction & stream network",
            "SCS-CN runoff + MUSLE sediment + soil-moisture bucket",
            "Zonal KPI analysis with real polygon geometry",
            "Keyline / pond / swale / check-dam design",
            "Design CRUD & GeoJSON/GPX/KML export",
            "Scenario comparison (baseline vs intervention)",
            "CHX water-permit compliance & breach risk",
            "Reactive runoff-risk alerts (Dunne/Hortonian)",
            "GIS-routing integration"
        ],
        "setup_parcel_url": "http://hydrology-api-service:8000/api/v1/hydrology/internal/setup-parcel",
        "backend_url": "http://hydrology-api-service:8000",
        "backend_only": false,
        "navigationItems": [
            { "path": "/hydrology", "label": "Water Studio", "icon": "droplets" }
        ],
        "api_prefix": "/api/v1/hydrology",
        "backend_service": "http://hydrology-api-service:8000"
    }'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name      = EXCLUDED.display_name,
    description       = EXCLUDED.description,
    version           = EXCLUDED.version,
    remote_entry_url  = EXCLUDED.remote_entry_url,
    is_active         = true,
    metadata          = EXCLUDED.metadata,
    updated_at        = NOW();
