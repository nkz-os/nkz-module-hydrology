"""
GeoLibreEngine — thin wrapper around geolibre-wasm for NKZ Water Studio.

Virtual I/O (bytes in, bytes out). No disk access.

WORKAROUND (geolibre-wasm 0.4.4): the standalone D8 tools
(`d8_pointer`, `d8_flow_accum`, `fd8_flow_accum`, `dinf_flow_accum`) trap with
a WASM 'unreachable' error on ANY DEM (verified, incl. breached). The composite
`flow_accum_full_workflow` works (it breaches + computes pointer + accumulation
in Rust), but 0.4.4 only materializes the accumulation output to a file — the
flow-direction pointer stays as an in-memory handle with no CLI flag to dump it.

Therefore:
  - flow accumulation  -> `flow_accum_full_workflow` (Rust, fast)
  - D8 flow pointer     -> `d8_pointer_esri()` derived in numpy from a breached
                           DEM (vectorized, no Python loops)
  - stream vectorization-> `raster_streams_to_vector` fed the numpy pointer

TODO: remove `d8_pointer_esri` + restore the native `d8_pointer` once
geolibre-wasm fixes the standalone D8 tools (tracked upstream). See
internal-docs-local/issues/geolibre-d8-trap.md.
"""

import logging
import tempfile
from typing import Optional

import geolibre_wasm as gl

logger = logging.getLogger(__name__)

# ESRI D8 flow-direction encoding: E=1 SE=2 S=4 SW=8 W=16 NW=32 N=64 NE=128
# Each tuple is (row offset, col offset, code).
_ESRI_D8 = [
    (0, 1, 1), (1, 1, 2), (1, 0, 4), (1, -1, 8),
    (0, -1, 16), (-1, -1, 32), (-1, 0, 64), (-1, 1, 128),
]


def d8_pointer_esri(z, nodata: Optional[float] = None):
    """ESRI-encoded D8 flow pointer from a depressionless (breached/filled) DEM.

    Steepest-descent over the 8 neighbours, fully vectorized (no wrap-around at
    borders). Sinks, border cells with no lower neighbour, and nodata cells get
    code 0 (no flow). Drop-in replacement for the geolibre-wasm 0.4.4
    `d8_pointer` tool, which traps. Returns a float32 ndarray of codes.
    """
    import numpy as np

    z = z.astype("float64")
    valid = np.ones(z.shape, dtype=bool)
    if nodata is not None:
        valid &= z != nodata

    best = np.zeros(z.shape, dtype="float64")        # best positive drop so far
    code = np.zeros(z.shape, dtype="float32")        # 0 = sink / edge / nodata
    for di, dj, c in _ESRI_D8:
        dist = (di * di + dj * dj) ** 0.5
        nb = np.full(z.shape, np.nan)
        si0, si1 = max(0, -di), z.shape[0] - max(0, di)
        sj0, sj1 = max(0, -dj), z.shape[1] - max(0, dj)
        nb[si0:si1, sj0:sj1] = z[si0 + di:si1 + di, sj0 + dj:sj1 + dj]
        drop = (z - nb) / dist
        m = valid & np.isfinite(drop) & (drop > best)
        best[m] = drop[m]
        code[m] = c
    code[~valid] = 0
    return code


class GeoLibreError(Exception):
    def __init__(self, tool_id: str, message: str, stdout: str = ""):
        self.tool_id = tool_id
        self.stdout = stdout
        super().__init__(f"[{tool_id}] {message}")


# Denylist: tools that crash with WASM unreachable in geolibre-wasm 0.4.4.
# Each maps to a clear error pointing to the workaround.
# All tools verified working in geolibre-wasm 0.5.1.
# Keep as safety net; if bugs resurface, add tool -> message entries here.
_BROKEN_TOOLS: dict[str, str] = {}


class GeoLibreEngine:
    """Wraps gl.run_tool() for hydrology operations. I/O is virtual.

    ALL gl.run_tool() calls go through this class. No other module should
    import geolibre_wasm or call gl.run_tool() directly.
    """

    def _run(self, tool_id: str, args: list[str],
             input_files: dict[str, bytes]) -> dict[str, bytes]:
        # Denylist check: reject known-broken tools with actionable message
        if tool_id in _BROKEN_TOOLS:
            raise GeoLibreError(
                tool_id,
                f"BROKEN: {_BROKEN_TOOLS[tool_id]}",
            )
        try:
            result = gl.run_tool(tool_id, args=args, input=input_files)
        except Exception as exc:  # WASM traps surface as Python exceptions
            raise GeoLibreError(tool_id, f"tool crashed: {exc}") from exc
        if result.exit_code != 0:
            raise GeoLibreError(tool_id, f"exit_code={result.exit_code}",
                                stdout=str(result.stdout))
        return result.files

    # ── DEM preprocessing ──────────────────────────────────────────────
    def fill_depressions(self, dem: bytes) -> bytes:
        """Fill all depressions (Wang & Liu). Verified working."""
        files = self._run("fill_depressions_wang_and_liu",
            ["--input=/work/dem.tif", "--output=/work/filled.tif", "--fix_flats"],
            {"dem.tif": dem})
        return files["filled.tif"]

    def breach_depressions(self, dem: bytes) -> bytes:
        """Breach depressions using least-cost path. Verified working."""
        files = self._run("breach_depressions_least_cost",
            ["--input=/work/dem.tif", "--output=/work/breached.tif"],
            {"dem.tif": dem})
        return files["breached.tif"]

    # ── Flow accumulation (composite workflow; standalone d8 is broken) ─
    def flow_accumulation(self, dem: bytes, out_type: str = "cells") -> bytes:
        """D8 flow accumulation via `flow_accum_full_workflow`.

        This composite tool breaches + computes pointer + accumulation in Rust
        and is the ONLY working flow-accumulation path in geolibre-wasm 0.4.4
        (the standalone `d8_flow_accum` traps). Only the accumulation raster is
        returned to a file; the internal pointer is not exposed (see module
        docstring) — use `d8_pointer()` for the pointer.
        """
        files = self._run("flow_accum_full_workflow",
            ["--input_dem=/work/dem.tif", "--output=/work/accum.tif",
             f"--out_type={out_type}"],
            {"dem.tif": dem})
        return files["accum.tif"]

    # ── D8 pointer (numpy workaround for the broken native tool) ────────
    def d8_pointer(self, breached_dem: bytes) -> bytes:
        """ESRI D8 flow pointer as a GeoTIFF, derived in numpy.

        Input MUST be a depressionless DEM (output of `breach_depressions` or
        `fill_depressions`). Preserves the input's CRS/transform so the
        vectorized streams are georeferenced. Workaround for the trapping
        native `d8_pointer` (geolibre-wasm 0.4.4).
        """
        import numpy as np
        import rasterio

        with tempfile.NamedTemporaryFile(suffix=".tif") as tin:
            tin.write(breached_dem)
            tin.flush()
            with rasterio.open(tin.name) as ds:
                z = ds.read(1)
                profile = ds.profile.copy()
                nodata = ds.nodata

        pointer = d8_pointer_esri(z, nodata=nodata)
        profile.update(dtype="float32", count=1, nodata=0)
        with tempfile.NamedTemporaryFile(suffix=".tif") as tout:
            with rasterio.open(tout.name, "w", **profile) as dst:
                dst.write(pointer.astype("float32"), 1)
            with open(tout.name, "rb") as f:
                return f.read()

    # ── Stream network ─────────────────────────────────────────────────
    def extract_streams(self, flow_accum: bytes, threshold: float = 1000.0) -> bytes:
        """Extract a stream raster from a flow-accumulation raster.

        NOTE: the real parameter is `flow_accumulation` (NOT `input`).
        """
        files = self._run("extract_streams",
            ["--flow_accumulation=/work/accum.tif", "--output=/work/streams.tif",
             f"--threshold={threshold}"],
            {"accum.tif": flow_accum})
        return files["streams.tif"]

    def streams_to_vector(self, streams: bytes, d8_pntr: bytes) -> bytes:
        """Vectorize a stream raster to GeoJSON using an ESRI D8 pointer.

        `d8_pntr` MUST be a real ESRI-encoded D8 pointer (from `d8_pointer()`);
        feeding any other raster yields geometrically wrong output even though
        the tool exits 0.
        """
        files = self._run("raster_streams_to_vector",
            ["--streams=/work/streams.tif", "--d8_pntr=/work/pntr.tif",
             "--output=/work/streams.geojson", "--esri_pntr"],
            {"streams.tif": streams, "pntr.tif": d8_pntr})
        return files["streams.geojson"]

    # ── Terrain derivatives ────────────────────────────────────────────
    def slope(self, dem: bytes, degrees: bool = True) -> bytes:
        args = ["--input=/work/dem.tif", "--output=/work/slope.tif"]
        if degrees:
            args.append("--units=degrees")
        return self._run("slope", args, {"dem.tif": dem})["slope.tif"]

    def aspect(self, dem: bytes) -> bytes:
        return self._run("aspect",
            ["--input=/work/dem.tif", "--output=/work/aspect.tif"],
            {"dem.tif": dem})["aspect.tif"]

    def wetness_index(self, sca: bytes, slope_raster: bytes) -> bytes:
        """TWI = ln(a / tan(beta)). Inputs: specific catchment area + slope."""
        return self._run("wetness_index",
            ["--sca=/work/sca.tif", "--slope=/work/slope.tif",
             "--output=/work/twi.tif"],
            {"sca.tif": sca, "slope.tif": slope_raster})["twi.tif"]

    # ── PMTiles (moved here to keep all gl.run_tool in one file) ─────
    def write_pmtiles(self, raster: bytes, colormap: str = "viridis",
                       min_zoom: int = 10, max_zoom: int = 18) -> bytes:
        """Convert a single-band raster to PMTiles archive."""
        files = self._run("write_pmtiles", [
            "--input=/work/raster.tif", "--output=/work/output.pmtiles",
            f"--colormap={colormap}",
            f"--min_zoom={min_zoom}", f"--max_zoom={max_zoom}",
        ], {"raster.tif": raster})
        return files["output.pmtiles"]

    # ── Catchment from point (numpy BFS, avoids broken basins) ────────
    def catchment_from_point(self, pointer_tif: bytes,
                              pour_col: int, pour_row: int) -> bytes:
        """Delineate upstream catchment from a pour point using D8 pointer.

        Uses numpy BFS upstream: a cell belongs to the catchment if its
        downslope neighbour (via D8 code) is already in the catchment.
        Avoids the broken `basins`/`subbasins` geolibre tools.

        Returns GeoTIFF bytes with 1=catchment, 0=outside.
        """
        import numpy as np
        import rasterio

        # D8 offsets + codes (ESRI encoding)
        D8 = {
            1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
            16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1),
        }
        # Reverse: for each cell, which neighbour flows INTO it
        # A cell (r,c) is in the catchment if any downstream neighbour
        # points to it. The neighbour's D8 code tells which direction.
        # The REVERSE direction is the one pointing at (r,c).
        REVERSE: dict[int, tuple[int, int]] = {
            1: (0, -1), 2: (-1, -1), 4: (-1, 0), 8: (-1, 1),
            16: (0, 1), 32: (1, 1), 64: (1, 0), 128: (1, -1),
        }

        with tempfile.NamedTemporaryFile(suffix=".tif") as tin:
            tin.write(pointer_tif)
            tin.flush()
            with rasterio.open(tin.name) as ds:
                pointer = ds.read(1)
                profile = ds.profile.copy()

        ny, nx = pointer.shape
        catchment = np.zeros((ny, nx), dtype=np.uint8)

        # BFS upstream from pour point
        from collections import deque
        q = deque()
        if 0 <= pour_row < ny and 0 <= pour_col < nx:
            catchment[pour_row, pour_col] = 1
            q.append((pour_row, pour_col))

        while q:
            r, c = q.popleft()
            # Check all 8 neighbours — if one points TO (r,c), it's upstream
            for code, (dr, dc) in REVERSE.items():
                nr, nc = r + dr, c + dc
                if 0 <= nr < ny and 0 <= nc < nx and catchment[nr, nc] == 0:
                    if int(pointer[nr, nc]) == code:
                        catchment[nr, nc] = 1
                        q.append((nr, nc))

        profile.update(dtype="uint8", count=1, nodata=0)
        with tempfile.NamedTemporaryFile(suffix=".tif") as tout:
            with rasterio.open(tout.name, "w", **profile) as dst:
                dst.write(catchment, 1)
            with open(tout.name, "rb") as f:
                return f.read()

    # ── Watershed / Basins ────────────────────────────────────────────
    def watershed(self, dem: bytes, pour_points: Optional[bytes] = None) -> bytes:
        """Delineate watershed from DEM with optional pour points."""
        inp = {"dem.tif": dem}
        args = ["--input=/work/dem.tif", "--output=/work/watershed.tif"]
        if pour_points:
            inp["points.shp"] = pour_points
            args.append("--pour_points=/work/points.shp")
        return self._run("watershed", args, inp)["watershed.tif"]

    def basins(self, dem: bytes) -> bytes:
        """Delineate drainage basins from DEM."""
        return self._run("basins",
            ["--input=/work/dem.tif", "--output=/work/basins.tif"],
            {"dem.tif": dem})["basins.tif"]

    # ── Convenience pipeline ──────────────────────────────────────────
    def run_dem_pipeline(self, dem: bytes) -> dict[str, bytes]:
        """Full DEM pipeline. Returns raster outputs + the vectorized drainage
        network (streams.geojson).

        Stream vectorization is RESTORED via the numpy D8 pointer workaround;
        it is no longer skipped.
        """
        breached = self.breach_depressions(dem)
        accum = self.flow_accumulation(dem)            # composite (internal breach)
        streams = self.extract_streams(accum, threshold=1000)
        pntr = self.d8_pointer(breached)               # numpy ESRI pointer
        streams_vec = self.streams_to_vector(streams, pntr)
        slope = self.slope(breached)
        aspect = self.aspect(breached)
        twi = self.wetness_index(accum, slope)
        return {
            "breached.tif": breached,
            "accum.tif": accum,
            "streams.tif": streams,
            "pntr.tif": pntr,
            "streams.geojson": streams_vec,
            "slope.tif": slope,
            "aspect.tif": aspect,
            "twi.tif": twi,
        }
