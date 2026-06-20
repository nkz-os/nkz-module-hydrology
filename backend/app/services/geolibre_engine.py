"""
GeoLibreEngine — thin wrapper around geolibre-wasm for NKZ Water Studio.

Virtual I/O (bytes in, bytes out). No disk access.

NOTE (geolibre-wasm 0.4.4 bug): d8_flow_accum, d8_pointer, fd8_flow_accum,
dinf_flow_accum crash with WASM 'unreachable' on this synthetic DEM.
Workaround: use flow_accum_full_workflow instead of d8_flow_accum.
raster_streams_to_vector requires d8_pntr which depends on d8_pointer —
this step is SKIPPED in Fase 0 pending a geolibre-wasm fix or version bump.
"""

import logging
from typing import Optional

import geolibre_wasm as gl

logger = logging.getLogger(__name__)


class GeoLibreError(Exception):
    def __init__(self, tool_id: str, message: str, stdout: str = ""):
        self.tool_id = tool_id
        self.stdout = stdout
        super().__init__(f"[{tool_id}] {message}")


class GeoLibreEngine:
    """Wraps gl.run_tool() for hydrology operations. I/O is virtual."""

    def _run(self, tool_id: str, args: list[str],
             input_files: dict[str, bytes]) -> dict[str, bytes]:
        result = gl.run_tool(tool_id, args=args, input=input_files)
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

    # ── Flow accumulation (workaround for d8_* bug) ───────────────────
    def flow_accumulation(self, dem: bytes) -> bytes:
        """Full workflow: fill + flow accumulation in one step.

        NOTE: Uses flow_accum_full_workflow as workaround for d8_flow_accum
        crash in geolibre-wasm 0.4.4. Replace with d8_flow_accum once fixed.
        """
        files = self._run("flow_accum_full_workflow",
            ["--input=/work/dem.tif", "--output=/work/accum.tif", "--out_type=cells"],
            {"dem.tif": dem})
        return files["accum.tif"]

    # This method is a placeholder for when d8_pointer is fixed.
    # def d8_pointer(self, dem: bytes) -> bytes: ...

    # ── Stream network ─────────────────────────────────────────────────
    def extract_streams(self, flow_accum: bytes, threshold: float = 1000.0) -> bytes:
        """Extract stream network from flow accumulation raster."""
        files = self._run("extract_streams",
            ["--input=/work/accum.tif", "--output=/work/streams.tif",
             f"--threshold={threshold}"],
            {"accum.tif": flow_accum})
        return files["streams.tif"]

    # raster_streams_to_vector is DEPENDENT on d8_pointer (crash bug).
    # Not implemented in Fase 0. Use GDAL/python-based vectorization instead
    # or wait for geolibre-wasm fix.

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

    # ── Convenience pipeline ──────────────────────────────────────────
    def run_dem_pipeline(self, dem: bytes) -> dict[str, bytes]:
        """Full DEM pipeline using verified working tools.

        Returns dict with keys: filled, accum, streams, slope, aspect, twi.
        Note: stream vectorization (raster_streams_to_vector) is SKIPPED
        due to d8_pointer crash in geolibre-wasm 0.4.4.
        """
        filled = self.fill_depressions(dem)
        accum = self.flow_accumulation(filled)
        streams = self.extract_streams(accum, threshold=1000)
        slope = self.slope(filled)
        aspect = self.aspect(filled)
        twi = self.wetness_index(accum, slope)
        return {
            "filled.tif": filled,
            "accum.tif": accum,
            "streams.tif": streams,
            "slope.tif": slope,
            "aspect.tif": aspect,
            "twi.tif": twi,
        }
