---
title: "Fase 0 Benchmark — geolibre-wasm"
description: "Performance benchmark of the geolibre-wasm DEM engine on a 200x200 synthetic DEM (Fase 0)."
sidebar.order: 3
---

# Fase 0 benchmark — geolibre-wasm (200×200 synthetic DEM @ 1m)

Date: 2026-06-20
WASM init time (first call): ~5.5s (one-time, includes WASM binary load)
After warmup (subsequent calls):

| Operation | geolibre-wasm (s) | Output (bytes) | Notes |
|---|---|---|---|
| fill_depressions | 0.057 | 158,367 | |
| flow_accumulation (full workflow) | 0.056 | 4,086 | `flow_accum_full_workflow` workaround |
| extract_streams | 0.156 | 1,804 | |
| slope | 0.072 | 135,873 | |
| aspect | 0.075 | 137,627 | |

**Known issue:** `d8_flow_accum`, `d8_pointer`, `fd8_flow_accum` crash with WASM `unreachable` in geolibre-wasm 0.4.4. Using `flow_accum_full_workflow` as workaround. `raster_streams_to_vector` requires `d8_pointer` — blocked until tool is fixed. File upstream issue or bump version when fixed.

Next: benchmark a real PNOA tile in Fase 1; compare vs WhiteboxTools native (gate: <2× slower).
