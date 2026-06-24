---
title: "NKZ Water Studio"
description: "DEM-based watershed and flow analysis for precision agriculture."
sidebar:
    order: 1
---

# NKZ Water Studio

**NKZ Water Studio** is the hydrology module of the Nekazari platform. It performs
DEM-based watershed delineation, stream-network extraction, and topographic
wetness index (TWI) computation, with water-harvesting modeling capabilities
under active development.

> **Status: beta.** The DEM analysis pipeline is operational; the full set of
> hydrological models (runoff, sediment, pond siting, keyline design) is in
> development.

## What it does (beta)

- **Watershed delineation** from a digital elevation model.
- **Stream network extraction** and vectorization.
- **Topographic Wetness Index (TWI)** for identifying saturation-prone zones.

## Roadmap

- Real DEM cascade (LiDAR → PNOA → IGN → Copernicus).
- Rainfall-runoff (SCS-CN), sediment yield (MUSLE), pond siting (pondScore).
- Keyline design, swale/check-dam sizing, multi-scenario comparison.
- Water Story 3D visualization in Cesium.

## Documentation

API reference is available at `/api/v1/hydrology/docs` once the module is running.
