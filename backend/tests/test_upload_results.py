"""Worker raster persistence: _upload_results must store derived rasters to
MinIO under the same key the design endpoints read (design_generator._raster_key).

Regression: _put_raster referenced an undefined `_parcel_short` (NameError),
silenced by `except Exception` in _upload_results -> design endpoints got no_data.
"""
from unittest.mock import MagicMock, patch

PARCEL = "urn:ngsi-ld:AgriParcel:tenant1:p1"
TENANT = "tenant1"


def _result():
    return {
        "twi.tif": b"twi-bytes",
        "streams.geojson": b"{}",
        "breached.tif": b"breached-bytes",
        "accum.tif": b"accum-bytes",
        "slope.tif": b"slope-bytes",
    }


def test_put_raster_uses_shared_short_key():
    """_put_raster must build the tenant-scoped key without raising NameError."""
    from app.workers.hydrology_worker import _put_raster

    s3 = MagicMock()
    with patch("app.services.s3.get_s3_client", return_value=s3):
        _put_raster(PARCEL, TENANT, "breached.tif", b"breached-bytes")

    assert s3.put_object.call_count == 1
    assert s3.put_object.call_args.kwargs["Key"] == "hydrology/tenant1/p1/breached.tif"
    assert s3.put_object.call_args.kwargs["Body"] == b"breached-bytes"


def test_upload_results_persists_streams_geojson():
    """streams.geojson must land under tile_service.stream_network_key's key
    (the check-dam endpoint reads it from there)."""
    from app.services.tile_service import stream_network_key
    from app.workers.hydrology_worker import _upload_results

    expected_key = stream_network_key(PARCEL, TENANT)
    assert expected_key == "hydrology/tenant1/p1/streams.geojson"

    s3 = MagicMock()
    with patch("app.services.s3.get_s3_client", return_value=s3):
        _upload_results(PARCEL, TENANT, _result())

    geojson_calls = [
        c for c in s3.put_object.call_args_list if c.kwargs["Key"] == expected_key
    ]
    assert len(geojson_calls) == 1
    assert geojson_calls[0].kwargs["Body"] == b"{}"
    assert geojson_calls[0].kwargs["ContentType"] == "application/geo+json"


def test_upload_results_persists_derived_rasters():
    """All three derived rasters land in MinIO under design_generator's key format."""
    from app.workers.hydrology_worker import _upload_results

    s3 = MagicMock()
    with patch("app.services.s3.get_s3_client", return_value=s3), \
         patch("app.workers.hydrology_worker.tile_service"), \
         patch("app.workers.hydrology_worker._put_geojson", create=True):
        _upload_results(PARCEL, TENANT, _result())

    stored = {c.kwargs["Key"]: c.kwargs["Body"] for c in s3.put_object.call_args_list}
    assert stored == {
        "hydrology/tenant1/p1/breached.tif": b"breached-bytes",
        "hydrology/tenant1/p1/accum.tif": b"accum-bytes",
        "hydrology/tenant1/p1/slope.tif": b"slope-bytes",
    }
