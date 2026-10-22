---
title: "NKZ Water Studio"
description: "DEM analysis, hydrological modeling, water-harvesting design, compliance and runoff-risk alerts for precision agriculture."
sidebar.order: 1
---

# NKZ Water Studio

**NKZ Water Studio** is the hydrology module of the Nekazari platform: DEM
analysis, hydrological modeling, water-harvesting design, regulatory compliance
and runoff-risk alerts.

> **Status:** feature-complete, pre-production hardening. The DEM pipeline,
> agronomic models (SCS-CN, MUSLE, soil-moisture bucket), design tools, scenario
> comparison, compliance and reactive alerts are wired end-to-end.

## What it does

- DEM cascade (eu-elevation) → flow direction/accumulation, stream network, slope, TWI.
- Hydrology models: SCS-CN runoff, MUSLE sediment, soil-moisture bucket, pond viability.
- Water-harvesting design: keyline, pond (with CHX compliance), swale, check dam; CRUD + GeoJSON/GPX/KML export.
- Zonal KPI analysis with real polygon geometry.
- Scenario comparison (baseline vs intervention) and reactive runoff-risk alerts.

## Documentation

- [Models reference](MODELS.md) — the numerical models.
- [README](../README.md) — architecture, endpoints, setup.
- API reference at `/api/v1/hydrology/docs` once the module is running.
