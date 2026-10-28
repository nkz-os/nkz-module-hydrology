"""Tests for design API endpoints."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient
from fastapi import FastAPI


def test_list_designs_query_uses_or_pipe():
    """list_designs must OR relationship terms with `|`, not `,` (NGSI-LD)."""
    from app.api import designs

    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        designs.list_designs(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))

    _, kwargs = MockOrion.return_value.query_entities.call_args
    q = kwargs["q"]
    assert q == f'(hasAgriParcel=="{pid}"|refAgriParcel=="{pid}")'
    assert "|" in q and "," not in q


def test_list_designs_queries_both_spec_types():
    """list_designs must query BOTH nkz:WaterStorage and nkz:OpenChannelFlow
    in one call via the comma-separated NGSI-LD typeSelection list (§6.1)."""
    from app.api import designs

    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        designs.list_designs(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))

    _, kwargs = MockOrion.return_value.query_entities.call_args
    assert kwargs["type"] == "nkz:WaterStorage,nkz:OpenChannelFlow"


def test_create_pond_uses_waterstorage_type_and_urn():
    """design_type 'pond' → nkz:WaterStorage with bare-type URN and MTQ capacity."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        designs.create_design(
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="pond",
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                parameters={
                    "capacity": 1500.0,
                    "pondScore": 0.82,
                    "isViable": True,
                    "requiresLining": False,
                },
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    (entity,), _ = MockOrion.return_value.create_entity.call_args
    assert entity["type"] == "nkz:WaterStorage"
    assert entity["id"].startswith("urn:ngsi-ld:WaterStorage:t1:p1:")
    # No nested full parcel URN in the id (audit fix).
    assert "AgriParcel" not in entity["id"]
    assert entity["nkz:capacity"]["value"] == 1500.0
    assert entity["nkz:capacity"]["unitCode"] == "MTQ"
    assert entity["nkz:pondScore"]["value"] == 0.82
    assert entity["nkz:isViable"]["value"] is True
    assert entity["nkz:requiresLining"]["value"] is False


def test_create_keyline_uses_openchannelflow_type_and_grade():
    """design_type 'keyline' → nkz:OpenChannelFlow with nkz:designGrade (%)."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        designs.create_design(
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="keyline",
                geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                parameters={"grade": 0.005},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    (entity,), _ = MockOrion.return_value.create_entity.call_args
    assert entity["type"] == "nkz:OpenChannelFlow"
    assert entity["id"].startswith("urn:ngsi-ld:OpenChannelFlow:t1:p1:")
    assert entity["nkz:designGrade"]["value"] == 0.5


def test_update_keyline_refreshes_design_grade():
    """PUT with a changed grade must PATCH nkz:designGrade with the new % value."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion, \
         patch.object(designs, "httpx") as mock_httpx:
        MockOrion.return_value.get_entity.return_value = {
            "nkz:version": {"value": 3},
        }
        designs.update_design(
            design_id="urn:ngsi-ld:OpenChannelFlow:t1:p1:d1",
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="keyline",
                geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                parameters={"grade": 0.008},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    _, kwargs = mock_httpx.patch.call_args
    attrs = kwargs["json"]
    assert attrs["nkz:designGrade"]["value"] == 0.8
    assert attrs["nkz:version"]["value"] == 4


def test_update_sends_context_link_header_without_env(monkeypatch):
    """PUT PATCH must carry a Link @context header even when CONTEXT_URL is unset.

    Regression: inject_fiware_headers only adds Link when the CONTEXT_URL env var
    is set. Hydrology prod does not set it, so nkz:* attrs would silently drop.
    """
    from app.api import designs

    monkeypatch.delenv("CONTEXT_URL", raising=False)

    with patch.object(designs, "SyncOrionClient") as MockOrion, \
         patch.object(designs, "httpx") as mock_httpx:
        MockOrion.return_value.get_entity.return_value = {"nkz:version": {"value": 1}}
        designs.update_design(
            design_id="urn:ngsi-ld:OpenChannelFlow:t1:p1:d1",
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="keyline",
                geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                parameters={"grade": 0.008},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    _, kwargs = mock_httpx.patch.call_args
    headers = kwargs["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "Link" in headers
    assert designs.get_settings().context_url in headers["Link"]
    assert 'rel="http://www.w3.org/ns/json-ld#context"' in headers["Link"]


def test_update_pond_refreshes_typed_attrs_with_unitcode():
    """Pond PUT with capacity must PATCH nkz:capacity carrying MTQ unitCode."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion, \
         patch.object(designs, "httpx") as mock_httpx:
        MockOrion.return_value.get_entity.return_value = {
            "nkz:version": {"value": 1},
        }
        designs.update_design(
            design_id="urn:ngsi-ld:WaterStorage:t1:p1:d1",
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="pond",
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                parameters={"capacity": 2000.0, "isViable": False},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    _, kwargs = mock_httpx.patch.call_args
    attrs = kwargs["json"]
    assert attrs["nkz:capacity"]["value"] == 2000.0
    assert attrs["nkz:capacity"]["unitCode"] == "MTQ"
    assert attrs["nkz:isViable"]["value"] is False


def test_list_designs_requires_auth():
    """Without auth headers, list_designs returns 401."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/design?parcel_id=p1")
    assert resp.status_code == 401


def test_create_design_requires_auth():
    """Without auth headers, create_design returns 401."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/design", json={
        "parcel_id": "urn:ngsi-ld:AgriParcel:p1",
        "design_type": "keyline",
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        "label": "Test",
    })
    assert resp.status_code == 401


def test_export_requires_auth():
    """Export endpoint requires auth (checked before format validation)."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/design/xxx/export?format=pdf")
    assert resp.status_code == 401


def test_export_gpx_returns_json_envelope():
    """gpx export must return a JSON envelope, not a raw application/gpx+xml body.

    The api-gateway auto-proxy 502s any non-JSON Content-Type, so the endpoint
    returns {filename, mediaType, content} and the frontend builds the Blob.
    """
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.return_value = {
            "location": {"value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
            "nkz:label": {"value": "My Keyline"},
        }
        out = designs.export_design(
            design_id="d1", format="gpx", auth=SimpleNamespace(tenant_id="t1"),
        )

    assert out["filename"] == "My Keyline.gpx"
    assert out["mediaType"] == "application/gpx+xml"
    assert out["content"].startswith("<?xml")
    assert "<gpx" in out["content"]


def test_export_kml_returns_json_envelope():
    """kml export must return a JSON envelope with the KML media type."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.return_value = {
            "location": {"value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
            "nkz:label": {"value": "My Swale"},
        }
        out = designs.export_design(
            design_id="d1", format="kml", auth=SimpleNamespace(tenant_id="t1"),
        )

    assert out["filename"] == "My Swale.kml"
    assert out["mediaType"] == "application/vnd.google-earth.kml+xml"
    assert "<kml" in out["content"]


def test_export_geojson_stays_feature():
    """geojson export is unchanged: a GeoJSON Feature (already JSON, gateway-safe)."""
    from app.api import designs

    geom = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.return_value = {
            "location": {"value": geom},
            "nkz:label": {"value": "GeoJSON Design"},
        }
        out = designs.export_design(
            design_id="d1", format="geojson", auth=SimpleNamespace(tenant_id="t1"),
        )

    assert out["type"] == "Feature"
    assert out["geometry"] == geom
    assert out["properties"]["name"] == "GeoJSON Design"


def test_generation_endpoints_require_auth():
    """All 4 generation endpoints require auth (return 401 without)."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    endpoints = [
        "/design/keyline/generate",
        "/design/keyline/jobs",
        "/design/pond/score",
        "/design/swale/suggest",
        "/design/check-dam/suggest",
    ]
    for url in endpoints:
        resp = client.post(url, json={"parcel_id": "p1"})
        assert resp.status_code == 401, f"{url} returned {resp.status_code}"


def test_get_design_404_hides_exception_text():
    """get_design 404 must NOT leak the underlying exception (Orion URLs/internals)."""
    from fastapi import HTTPException
    from app.api import designs

    secret = "orion-internal-http://orion:1026/secret-path"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.side_effect = RuntimeError(secret)
        with pytest.raises(HTTPException) as exc:
            designs.get_design(design_id="d1", auth=SimpleNamespace(tenant_id="t1"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Design not found"
    assert secret not in str(exc.value.detail)


def test_create_design_500_hides_exception_text():
    """create_design 500 must return a generic detail, not str(e)."""
    from fastapi import HTTPException
    from app.api import designs

    secret = "orion-internal-http://orion:1026/secret-path"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.create_entity.side_effect = RuntimeError(secret)
        with pytest.raises(HTTPException) as exc:
            designs.create_design(
                req=designs.DesignSaveRequest(
                    parcel_id="urn:ngsi-ld:AgriParcel:p1",
                    design_type="keyline",
                    geometry={"type": "Point", "coordinates": [0, 0]},
                ),
                auth=SimpleNamespace(tenant_id="t1"),
            )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Internal error"
    assert secret not in str(exc.value.detail)


def test_score_pond_returns_compliance_block():
    """score_pond must surface a CHX compliance block (Phase 2.1)."""
    import io as _io
    import numpy as np
    import rasterio
    from app.api import designs

    # Flat DEM (slope 0 -> breach risk driven only by volume).
    z = np.full((20, 20), 100.0, dtype="float32")
    buf = _io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=20, width=20, count=1, dtype="float32",
        crs="EPSG:4326",
        transform=rasterio.transform.from_origin(-1.645, 42.822, 0.001, 0.001),
    ) as dst:
        dst.write(z, 1)

    with patch.object(designs, "download_raster", return_value=buf.getvalue()):
        resp = designs.score_pond(
            req=designs.PondScoreRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                center=[-1.635, 42.812], radius=30.0, depth=2.0, basin="CH_Segura",
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )
    assert resp["status"] == "ok"
    comp = resp["compliance"]
    assert comp["basis"] == "storage_capacity"
    assert comp["basin"] == "CH_Segura"
    assert comp["permitThresholdM3"] == 3000  # CH_Segura threshold
    # storage capacity = π·30²·2 ≈ 5654.9 m³ > 3000 -> permit required.
    assert comp["storageCapacityM3"] == round(np.pi * 30 ** 2 * 2, 1)
    assert comp["requiresPermit"] is True
    # breach risk: volume > 5000 (+1), flat slope, no downstream -> low.
    assert comp["breachRisk"] == "low"
    assert comp["disclaimer"]
    assert comp["downstreamExposure"]["hasExposure"] is False


# ── Keyline endpoint ───────────────────────────────────────────────────

def _keyline_rasters(cell=1.0, size=80, flat=False):
    import io
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    tf = from_origin(600000, 4700000, cell, cell)
    i = np.arange(size)[:, None].astype(float)
    j = np.arange(size)[None, :].astype(float)
    floor = np.where(i <= 40, 120 - 0.5 * i, 100 - 0.05 * (i - 40))
    # rounded valley floor (a sharp V cannot hold a keyline within the 1.5 %
    # line grade cap: the trace hugs the steep sides)
    dem = np.full((size, size), 100.0) if flat else floor + 0.15 * (np.sqrt((j - 40) ** 2 + 9.0) - 3)
    acc = np.zeros((size, size))
    if not flat:
        for r in range(size):
            acc[r, 40] = 80 - r
    out = {}
    for name, arr in (("breached.tif", dem), ("accum.tif", acc)):
        buf = io.BytesIO()
        with rasterio.open(buf, "w", driver="GTiff", height=size, width=size, count=1,
                           dtype="float32", crs="EPSG:25830", transform=tf) as dst:
            dst.write(arr.astype("float32"), 1)
        out[name] = buf.getvalue()
    return out


def _parcel_wgs(size=80, cell=1.0, margin=5):
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
    x0, x1 = 600000 + margin, 600000 + size * cell - margin
    y1, y0 = 4700000 - margin, 4700000 - size * cell + margin
    ring = [t.transform(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return {"type": "Polygon", "coordinates": [[list(c) for c in ring]]}


def _call_keyline(rasters, parcel=None, **req):
    from app.api import designs
    from app.services import design_generator

    entity = {"location": {"type": "GeoProperty", "value": parcel}} if parcel else {}
    with patch.object(design_generator, "download_raster",
                      side_effect=lambda pid, ten, name: rasters.get(name)), \
         patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.return_value = entity
        return designs.generate_keyline(
            req=designs.KeylineRequest(parcel_id="p-1", spacing=6.0, **req),
            auth=SimpleNamespace(tenant_id="tenant-a"),
        )


def test_keyline_response_keeps_legacy_fields_and_adds_arrays():
    res = _call_keyline(_keyline_rasters(), _parcel_wgs(), lines=2, min_line_m=20.0)
    assert res["status"] == "ok"
    assert res["keypoint"]["type"] == "Point"
    assert res["keyline"]["type"] == "LineString"
    assert len(res["keypoints"]) == 1 and len(res["keylines"]) == 1
    assert res["keypoints"][0] == res["keypoint"]
    assert res["parallel_lines"]
    assert len(res["keylines_metrics"]) == len(res["keylines"])
    assert set(res["keyline_metrics"]) == {"grade", "max_grade_20m"}
    for p in res["parallel_lines"]:
        assert set(p) == {"geometry", "grade", "max_grade_20m", "direction"}
        assert p["direction"] == "line"
        assert p["geometry"]["type"] == "LineString"
        assert 0 <= p["grade"] <= p["max_grade_20m"] <= res["max_line_grade"] == 0.015
    assert 0 < res["coverage_pct"] <= 100 and res["request"]["min_line_m"] == 20.0
    assert res["request"]["lines"] == 2


def test_keyline_lines_optional_covers_parcel():
    # a 70 m parcel: lines down to 30 m (the 100 m default holds none here)
    capped = _call_keyline(_keyline_rasters(), _parcel_wgs(), lines=1, min_line_m=30.0)
    full = _call_keyline(_keyline_rasters(), _parcel_wgs(), min_line_m=30.0)
    assert full["request"]["lines"] is None
    assert len(full["parallel_lines"]) > len(capped["parallel_lines"])


def test_keyline_refused_on_coarse_dem():
    res = _call_keyline(_keyline_rasters(cell=25.0), _parcel_wgs(cell=25.0))
    assert res["status"] == "terrain_too_coarse"
    assert "keyline" not in res


def test_keyline_no_keypoint_on_flat():
    res = _call_keyline(_keyline_rasters(flat=True), _parcel_wgs())
    assert res["status"] == "no_keypoint"


def test_keyline_no_polygon_is_no_data():
    assert _call_keyline(_keyline_rasters(), None)["status"] == "no_data"


def test_keyline_all_coordinates_inside_parcel():
    from shapely.geometry import shape
    parcel = _parcel_wgs()
    res = _call_keyline(_keyline_rasters(), parcel)
    poly = shape(parcel).buffer(1e-6)
    geoms = res["keylines"] + [p["geometry"] for p in res["parallel_lines"]]
    assert geoms
    for g in geoms:
        assert poly.covers(shape(g))


def test_keyline_clipped_to_offgrid_parcel():
    from shapely.geometry import shape
    for margin in (5.2, 5.37, 5.5, 5.63, 5.8):  # polygon edges not cell aligned
        parcel = _parcel_wgs(margin=margin)
        res = _call_keyline(_keyline_rasters(), parcel)
        assert res["status"] == "ok"
        poly = shape(parcel).buffer(1e-6)
        geoms = [res["keyline"]] + res["keylines"] + [p["geometry"] for p in res["parallel_lines"]]
        for g in geoms:
            assert poly.covers(shape(g)), margin


def test_keyline_orion_failure_is_502_not_no_data():
    from fastapi import HTTPException
    from app.api import designs
    from app.services import design_generator

    rasters = _keyline_rasters()
    with patch.object(design_generator, "download_raster",
                      side_effect=lambda pid, ten, name: rasters.get(name)), \
         patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.side_effect = RuntimeError("boom")
        with pytest.raises(HTTPException) as exc:
            designs.generate_keyline(
                req=designs.KeylineRequest(parcel_id="p-1"),
                auth=SimpleNamespace(tenant_id="tenant-a"),
            )
    assert exc.value.status_code == 502
    assert exc.value.detail["status"] == "orion_unavailable"
    assert "boom" not in str(exc.value.detail)


def test_keyline_request_rejects_invalid_inputs():
    from pydantic import ValidationError
    from app.api.designs import KeylineRequest
    assert KeylineRequest(parcel_id="p-1").min_line_m == 100.0
    for bad in ({"spacing": 0}, {"grade": -0.1}, {"lines": -1}, {"min_line_m": 0}):
        with pytest.raises(ValidationError):
            KeylineRequest(parcel_id="p-1", **bad)


def _valley_rasters(cell, size_m=160.0, furrow=0.0, nodata_boxes=()):
    """Valley falling south (slope break 80 m down) as GeoTIFFs tagged with
    nodata=-9999; `nodata_boxes` are (x0, y0, x1, y1) metre boxes from the
    top-left corner written as nodata in both rasters."""
    import io
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    n = int(size_m / cell)
    i, j = np.mgrid[0:n, 0:n].astype(float)
    y, x = (i + 0.5) * cell, (j + 0.5) * cell
    floor = np.where(y <= 80, 130 - 0.25 * y, 110 - 0.025 * (y - 80))
    dem = floor + (np.sqrt((x - 80) ** 2 + 9.0) - 3) * 0.15 + furrow * np.sin(2 * np.pi * x)
    acc = np.zeros((n, n))
    acc[:, int(80 / cell)] = (np.arange(n) + 1) * 4.0
    for x0, y0, x1, y1 in nodata_boxes:
        sel = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        dem[sel] = -9999.0
        acc[sel] = -9999.0
    tf = from_origin(600000, 4700000, cell, cell)
    out = {}
    for name, arr in (("breached.tif", dem), ("accum.tif", acc)):
        buf = io.BytesIO()
        with rasterio.open(buf, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32",
                           crs="EPSG:25830", transform=tf, nodata=-9999.0) as dst:
            dst.write(arr.astype("float32"), 1)
        out[name] = buf.getvalue()
    return out


def _utm(geom):
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    t = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
    return transform(t.transform, shape(geom))


def test_keyline_with_nodata_gaps_inside_parcel():
    from shapely.geometry import box, shape
    from shapely.ops import unary_union
    rasters = _valley_rasters(1.0, nodata_boxes=[
        (77, 150, 83, 156),     # on the valley floor near the outlet
        (84, 100, 90, 106),     # on the path of the east arm of the keyline
        (0, 0, 40, 160),        # a strip wider than the fill distance
    ])
    parcel = _parcel_wgs(size=160)
    res = _call_keyline(rasters, parcel, min_line_m=30.0)
    assert res["status"] == "ok"
    kp = _utm(res["keypoint"])
    assert 100 < res["keypoint"]["coordinates"][2] < 140      # a real elevation
    assert abs(kp.x - 600080) <= 4 and abs(4700000 - kp.y - 80) <= 4
    # the keyline crosses the slope on both sides of the valley (the gap on
    # the east arm is filled, not a cliff the trace turns back from)
    ends = [x - 600000 for x, _ in _utm(res["keyline"]).coords[::len(_utm(res["keyline"]).coords) - 1]]
    assert min(ends) < 75 and max(ends) > 85
    poly = shape(parcel).buffer(1e-6)
    geoms = res["keylines"] + [p["geometry"] for p in res["parallel_lines"]]
    for g in geoms:
        assert poly.covers(shape(g))
    lines = [_utm(g) for g in geoms]
    area = _utm(parcel)
    covered = unary_union([g.buffer(3.0) for g in lines]).intersection(area).area / area.area
    assert res["coverage_pct"] == pytest.approx(100 * covered, abs=0.1)
    # nothing over the part of the strip the fill cannot reach (> 20 m from data)
    unfilled = box(600000, 4699840, 600015, 4700000)
    assert not any(g.intersects(unfilled) for g in lines)


def test_keyline_on_fine_dem_with_furrows():
    """0.5 m terrain with plough furrows: the trace runs on the analysis grid,
    not on the furrows."""
    res = _call_keyline(_valley_rasters(0.5, furrow=0.08), _parcel_wgs(size=160))
    assert res["status"] == "ok"
    assert _utm(res["keyline"]).length > 50


def _sharp_v_rasters(size=80):
    """A 50 % V valley: on the 2 m analysis grid its keyline cannot hold the
    1.5 % line cap, so the pattern is made of guides only."""
    import io
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    i = np.arange(size)[:, None].astype(float)
    j = np.arange(size)[None, :].astype(float)
    dem = np.where(i <= 40, 120 - 0.5 * i, 100 - 0.05 * (i - 40)) + 0.5 * np.abs(j - 40)
    acc = np.zeros((size, size))
    acc[:, 40] = 80 - np.arange(size)
    out = {}
    for name, arr in (("breached.tif", dem), ("accum.tif", acc)):
        buf = io.BytesIO()
        with rasterio.open(buf, "w", driver="GTiff", height=size, width=size, count=1, dtype="float32",
                           crs="EPSG:25830", transform=from_origin(600000, 4700000, 1.0, 1.0)) as dst:
            dst.write(arr.astype("float32"), 1)
        out[name] = buf.getvalue()
    return out


def test_keyline_ok_without_keyline_but_with_lines():
    res = _call_keyline(_sharp_v_rasters(), _parcel_wgs(), min_line_m=20.0)
    assert res["status"] == "ok"
    assert res["keyline"] is None and res["keylines"] == [] and res["keyline_metrics"] is None
    assert res["keypoint"]["type"] == "Point"
    assert any(p["direction"] == "line" for p in res["parallel_lines"])
    assert res["coverage_truncated"] is False


def test_keyline_reports_and_logs_truncated_coverage(monkeypatch, caplog):
    import logging
    from app.services import keyline

    for limit, value, reason in (("MAX_FAILED_SEEDS", 0, "seed_limit"),
                                 ("LAYOUT_TIME_BUDGET_S", 0.0, "time_budget")):
        with monkeypatch.context() as m:
            m.setattr(keyline, limit, value)
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="app.api.designs"):
                res = _call_keyline(_valley_rasters(1.0), _parcel_wgs(size=160))
        assert res["status"] == "ok" and res["coverage_truncated"] is True
        assert "stopped_by" not in res                  # response contract unchanged
        assert any(reason in r.getMessage() and "p-1" in r.getMessage() for r in caplog.records)


def test_keyline_self_crossing_parcel_with_nodata_is_made_valid():
    """A parcel ring that crosses itself (a bow-tie at its south end) over a
    DEM with nodata gaps is made valid instead of failing."""
    import shapely
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
    corners = ((5, 5), (155, 5), (155, 130), (5, 155), (155, 155), (5, 130), (5, 5))
    ring = [t.transform(600000 + x, 4700000 - y) for x, y in corners]
    parcel = {"type": "Polygon", "coordinates": [[list(c) for c in ring]]}
    rasters = _valley_rasters(1.0, nodata_boxes=[(84, 100, 90, 106), (0, 0, 40, 160)])
    res = _call_keyline(rasters, parcel, min_line_m=30.0)
    assert res["status"] == "ok"
    valid = shapely.make_valid(_utm(parcel)).buffer(1e-3)
    for g in res["keylines"] + [p["geometry"] for p in res["parallel_lines"]]:
        assert valid.covers(_utm(g))
    assert 0 < res["coverage_pct"] <= 100


def test_keyline_parcel_without_area_is_no_data():
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
    ring = [t.transform(x, y) for x, y in ((600010, 4699900), (600100, 4699900), (600010, 4699900))]
    parcel = {"type": "Polygon", "coordinates": [[list(c) for c in ring + ring[:1]]]}
    res = _call_keyline(_keyline_rasters(), parcel)
    assert res["status"] == "no_data"


def test_keyline_dem_in_geographic_crs_is_refused():
    import io
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    out = {}
    for name in ("breached.tif", "accum.tif"):
        buf = io.BytesIO()
        with rasterio.open(buf, "w", driver="GTiff", height=40, width=40, count=1, dtype="float32",
                           crs="EPSG:4326", transform=from_origin(-1.6, 42.8, 1e-5, 1e-5)) as dst:
            dst.write(np.arange(1600, dtype="float32").reshape(40, 40), 1)
        out[name] = buf.getvalue()
    res = _call_keyline(out, _parcel_wgs())
    assert res["status"] == "no_data" and "projected" in res["detail"]
    assert "keyline" not in res


def test_keyline_job_endpoint_enqueues_with_tenant_third():
    from app.api import designs

    queued = {}

    class FakeQueue:
        def __init__(self, name, connection=None):
            queued["name"] = name

        def enqueue(self, fn, args, job_id, job_timeout, result_ttl):
            queued.update(fn=fn, args=args, job_id=job_id, timeout=job_timeout)

    with patch("rq.Queue", FakeQueue), patch("redis.Redis.from_url"):
        res = designs.start_keyline_job(
            req=designs.KeylineRequest(parcel_id="p-1", spacing=6.0, min_line_m=50.0),
            auth=SimpleNamespace(tenant_id="tenant-a"),
        )
    from app.workers.keyline_worker import run_keyline_job
    assert res["status"] == "queued" and res["job_id"] == queued["job_id"]
    assert queued["name"] == "hydrology-processing" and queued["fn"] is run_keyline_job
    pid, jid, tenant, params = queued["args"]
    assert (pid, jid, tenant) == ("p-1", res["job_id"], "tenant-a")   # /jobs scopes by args[2]
    assert params["spacing"] == 6.0 and params["min_line_m"] == 50.0


def _run_job(rasters, parcel, **params):
    from app.api import designs
    from app.services import design_generator
    from app.workers.keyline_worker import run_keyline_job

    entity = {"location": {"type": "GeoProperty", "value": parcel}} if parcel else {}
    with patch.object(design_generator, "download_raster",
                      side_effect=lambda pid, ten, name: rasters.get(name)), \
         patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.return_value = entity
        return run_keyline_job("p-1", "job-1", "tenant-a", {"parcel_id": "p-1", "spacing": 6.0, **params})


def test_keyline_job_returns_the_sync_response():
    rasters, parcel = _valley_rasters(1.0), _parcel_wgs(size=160)
    job = _run_job(rasters, parcel)
    sync = _call_keyline(rasters, parcel)
    assert job["status"] == "ok"
    assert job["keylines"] == sync["keylines"] and job["parallel_lines"] == sync["parallel_lines"]


def test_keyline_job_uses_the_longer_budget(monkeypatch):
    from app.services import keyline

    monkeypatch.setattr(keyline, "LAYOUT_TIME_BUDGET_S", 0.0)  # would stop the sync call at once
    job = _run_job(_valley_rasters(1.0), _parcel_wgs(size=160))
    assert job["status"] == "ok" and job["coverage_truncated"] is False


def test_keyline_job_broker_failure_is_a_status_not_a_crash():
    from app.api import designs
    from app.services import design_generator
    from app.workers.keyline_worker import run_keyline_job

    rasters = _keyline_rasters()
    with patch.object(design_generator, "download_raster",
                      side_effect=lambda pid, ten, name: rasters.get(name)), \
         patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.side_effect = RuntimeError("boom")
        res = run_keyline_job("p-1", "job-1", "tenant-a", {"parcel_id": "p-1"})
    assert res["status"] == "orion_unavailable" and "boom" not in str(res)


def test_keyline_job_ignores_parcel_id_in_params():
    # The parcel comes from the job arguments, never from the stored params.
    from app.services import design_generator
    from app.workers.keyline_worker import run_keyline_job

    seen = []
    with patch.object(design_generator, "download_raster",
                      side_effect=lambda pid, ten, name: seen.append((pid, ten)) or None):
        res = run_keyline_job("p-1", "job-1", "tenant-a", {"parcel_id": "p-other"})
    assert res["status"] == "no_data"
    assert seen and all(c == ("p-1", "tenant-a") for c in seen)
