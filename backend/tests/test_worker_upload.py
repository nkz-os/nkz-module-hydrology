"""_upload_results persists the four derived rasters, in order."""
from unittest.mock import patch

from app.workers import hydrology_worker

PARCEL = "urn:ngsi-ld:AgriParcel:acme:p1"
TENANT = "acme"


def _result(**overrides):
    base = {
        "streams.geojson": b"{}",
        "breached.tif": b"b",
        "accum.tif": b"a",
        "slope.tif": b"s",
        "twi.tif": b"t",
    }
    base.update(overrides)
    return base


def test_upload_results_uploads_four_rasters_in_order():
    with patch.object(hydrology_worker, "_put_geojson") as geo, \
         patch.object(hydrology_worker, "_put_raster") as put:
        hydrology_worker._upload_results(PARCEL, TENANT, _result())
    geo.assert_called_once()
    assert [c.args[2] for c in put.call_args_list] == [
        "breached.tif", "accum.tif", "slope.tif", "twi.tif",
    ]
    assert put.call_args_list[3].args[3] == b"t"


def test_upload_results_skips_missing_twi_with_warning(caplog):
    result = _result()
    del result["twi.tif"]
    with patch.object(hydrology_worker, "_put_geojson"), \
         patch.object(hydrology_worker, "_put_raster") as put, \
         caplog.at_level("WARNING"):
        hydrology_worker._upload_results(PARCEL, TENANT, result)
    assert [c.args[2] for c in put.call_args_list] == [
        "breached.tif", "accum.tif", "slope.tif",
    ]
    assert any("twi.tif" in r.getMessage() for r in caplog.records)
