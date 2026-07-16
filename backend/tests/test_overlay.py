"""Tests for the TWI PNG overlay service + endpoint.

The overlay endpoint returns JSON (presigned PNG URL + WGS84 bounds) — NEVER
image bytes, because the api-gateway 502s any non-JSON response. The browser
fetches the PNG straight from the private MinIO bucket via the presigned URL.
"""
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

UTM_CRS = "EPSG:25830"
_TRANSFORM = from_origin(500000, 4750000, 5, 5)
_N = 40
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _synthetic_twi_tif() -> bytes:
    """40x40 ETRS89/UTM-30N TWI GeoTIFF with a nodata corner."""
    j = np.arange(_N)
    i = np.arange(_N)
    J, I = np.meshgrid(j, i)
    twi = 5.0 + np.abs(J - _N / 2) * 0.3 + (I / _N) * 4.0
    twi = twi.astype(np.float32)
    nodata = -9999.0
    twi[:5, :5] = nodata  # nodata block in the top-left corner
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=_N, width=_N, count=1,
        dtype="float32", crs=UTM_CRS, transform=_TRANSFORM, nodata=nodata,
    ) as dst:
        dst.write(twi, 1)
    return buf.getvalue()


def _in_spain_bounds(b: dict) -> bool:
    return (
        -10.0 <= b["west"] <= 0.0 and -10.0 <= b["east"] <= 0.0
        and 35.0 <= b["south"] <= 45.0 and 35.0 <= b["north"] <= 45.0
        and b["west"] < b["east"] and b["south"] < b["north"]
    )


class TestRenderOverlay:
    def test_render_returns_png_and_bounds(self):
        from app.services.overlay import render_twi_overlay

        png, bounds = render_twi_overlay(_synthetic_twi_tif())
        assert png[:8] == _PNG_MAGIC
        assert _in_spain_bounds(bounds)

    def test_nodata_pixel_is_transparent(self):
        from PIL import Image
        from app.services.overlay import render_twi_overlay

        png, _ = render_twi_overlay(_synthetic_twi_tif())
        img = Image.open(io.BytesIO(png))
        assert img.mode == "RGBA"
        assert img.size == (_N, _N)
        # top-left corner is nodata -> alpha 0
        assert img.getpixel((0, 0))[3] == 0
        # a valid interior pixel -> semi-opaque
        assert img.getpixel((_N - 1, _N - 1))[3] > 0

    def test_bounds_use_corner_envelope(self):
        from app.services.overlay import render_twi_overlay

        _, bounds = render_twi_overlay(_synthetic_twi_tif())
        # raster spans 200m; a fraction of a degree, positive extent
        assert 0 < (bounds["east"] - bounds["west"]) < 0.05
        assert 0 < (bounds["north"] - bounds["south"]) < 0.05


class TestEnsureOverlay:
    def _settings(self):
        return SimpleNamespace(minio_bucket="nkz-hydrology")

    def test_cache_hit_skips_render(self):
        """When PNG + bounds already exist in MinIO, no render/upload happens."""
        from app.services import overlay

        s3 = MagicMock()
        bounds = {"west": -1.0, "south": 42.0, "east": -0.9, "north": 42.1}
        s3.get_object.return_value = {
            "Body": io.BytesIO(b'{"west": -1.0, "south": 42.0, "east": -0.9, "north": 42.1}')
        }
        s3.head_object.return_value = {}

        with patch.object(overlay, "_s3_client", return_value=s3), \
             patch.object(overlay, "get_settings", return_value=self._settings()), \
             patch("app.services.design_generator.download_raster") as dl, \
             patch.object(overlay, "render_twi_overlay") as render:
            out = overlay.ensure_twi_overlay("urn:ngsi-ld:AgriParcel:p1", "t7")

        render.assert_not_called()
        dl.assert_not_called()
        s3.put_object.assert_not_called()
        assert out == bounds

    def test_missing_tif_returns_none(self):
        from app.services import overlay

        s3 = MagicMock()
        s3.head_object.side_effect = Exception("404")

        with patch.object(overlay, "_s3_client", return_value=s3), \
             patch.object(overlay, "get_settings", return_value=self._settings()), \
             patch("app.services.design_generator.download_raster", return_value=None):
            out = overlay.ensure_twi_overlay("urn:ngsi-ld:AgriParcel:p1", "t7")

        assert out is None
        s3.put_object.assert_not_called()

    def test_render_path_uploads_png_and_bounds(self):
        from app.services import overlay

        s3 = MagicMock()
        s3.head_object.side_effect = Exception("404")

        with patch.object(overlay, "_s3_client", return_value=s3), \
             patch.object(overlay, "get_settings", return_value=self._settings()), \
             patch("app.services.design_generator.download_raster",
                   return_value=_synthetic_twi_tif()):
            out = overlay.ensure_twi_overlay("urn:ngsi-ld:AgriParcel:p1", "t7")

        assert _in_spain_bounds(out)
        # two uploads: the PNG and the sibling bounds JSON
        assert s3.put_object.call_count == 2
        keys = [c.kwargs.get("Key") for c in s3.put_object.call_args_list]
        assert any(k.endswith("twi_overlay.png") for k in keys)
        assert any(k.endswith("twi_overlay_bounds.json") for k in keys)


class TestOverlayEndpoint:
    def test_not_generated_shape(self):
        import asyncio
        from app.api import visualization

        ctx = SimpleNamespace(tenant_id="t7", user_id="u1")
        with patch("app.services.overlay.ensure_twi_overlay", return_value=None):
            out = asyncio.run(
                visualization.get_twi_overlay("urn:ngsi-ld:AgriParcel:p1", ctx)
            )
        assert out == {"url": None, "bounds": None, "status": "not_generated"}

    def test_ok_shape(self):
        import asyncio
        from app.api import visualization

        ctx = SimpleNamespace(tenant_id="t7", user_id="u1")
        bounds = {"west": -1.0, "south": 42.0, "east": -0.9, "north": 42.1}
        with patch("app.services.overlay.ensure_twi_overlay", return_value=bounds), \
             patch("app.services.tile_service.get_public_url",
                   return_value="https://minio.example/presigned"):
            out = asyncio.run(
                visualization.get_twi_overlay("urn:ngsi-ld:AgriParcel:p1", ctx)
            )
        assert out["status"] == "ok"
        assert out["bounds"] == bounds
        assert out["url"] == "https://minio.example/presigned"
