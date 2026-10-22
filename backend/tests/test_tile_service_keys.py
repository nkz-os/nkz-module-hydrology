"""MinIO keys MUST be tenant-scoped (hermeticity)."""
from app.services.tile_service import stream_network_key


def test_stream_key_is_tenant_scoped():
    k = stream_network_key("urn:ngsi-ld:AgriParcel:p1", tenant_id="t7")
    assert k.startswith("hydrology/t7/p1/")
    assert k.endswith(".geojson")
