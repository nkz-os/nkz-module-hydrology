"""Tests for LiDAR DTM discovery/fetch (cross-module: hydrology ← lidar).

Contract (internal-docs-local/2026-09-02-lidar-vertical-fix-cross-module-plan.md):
discovery via Orion-LD DigitalAsset (tenant-scoped), artifacts via internal S3
read of bucket lidar-tilesets — never the public MinIO URL (hairpin NAT).
"""
import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lidar_dem import (
    LIDAR_TILESETS_BUCKET,
    fetch_dtm_bytes,
    find_latest_lidar_asset,
)


def _asset(
    entity_id,
    parcel_urn="urn:ngsi-ld:AgriParcel:p1",
    status="completed",
    observed="2026-09-01T10:00:00Z",
    with_dtm=True,
):
    e = {
        "id": f"urn:ngsi-ld:DigitalAsset:{entity_id}",
        "assetCategory": {"type": "Property", "value": "LiDAR"},
        "processingStatus": {"type": "Property", "value": status},
        "dateObserved": {"type": "Property", "value": observed},
        "hasAgriParcel": {"type": "Relationship", "object": parcel_urn},
    }
    if with_dtm:
        e["dtmUrl"] = {
            "type": "Property",
            "value": f"https://minio.example.com/lidar-tilesets/{entity_id}/dtm.tif",
        }
    return e


@contextmanager
def _orion_mock(entities):
    with patch("app.services.lidar_dem.OrionClient") as oc:
        inst = MagicMock()
        inst.query_entities = AsyncMock(return_value=entities)
        inst.close = AsyncMock()
        oc.return_value = inst
        yield inst


class TestFindLatestLidarAsset:
    def test_picks_latest_completed(self):
        gen = _orion_mock([
            _asset("old", observed="2026-01-01T00:00:00Z"),
            _asset("new", observed="2026-09-01T00:00:00Z"),
            _asset("newer-broken", observed="2026-09-02T00:00:00Z", status="failed"),
        ])
        with gen as inst:
            asset = asyncio.run(find_latest_lidar_asset("t1", "p1"))
        assert asset is not None
        assert asset.asset_id == "new"
        inst.query_entities.assert_awaited_once()

    def test_skips_assets_without_dtm(self):
        with _orion_mock([_asset("nodtm", with_dtm=False)]) as inst:
            assert asyncio.run(find_latest_lidar_asset("t1", "p1")) is None

    def test_none_when_no_assets(self):
        with _orion_mock([]):
            assert asyncio.run(find_latest_lidar_asset("t1", "p1")) is None

    def test_short_parcel_id_builds_urn_and_filters(self):
        with _orion_mock([]) as inst:
            asyncio.run(find_latest_lidar_asset("t1", "abc123"))
        kwargs = inst.query_entities.await_args.kwargs
        assert kwargs.get("type") == "DigitalAsset"
        assert 'hasAgriParcel=="urn:ngsi-ld:AgriParcel:abc123"' in kwargs.get("q", "")
        assert 'processingStatus=="completed"' in kwargs.get("q", "")

    def test_urn_parcel_id_kept_as_is(self):
        with _orion_mock([]) as inst:
            asyncio.run(
                find_latest_lidar_asset("t1", "urn:ngsi-ld:AgriParcel:abc123")
            )
        kwargs = inst.query_entities.await_args.kwargs
        assert 'hasAgriParcel=="urn:ngsi-ld:AgriParcel:abc123"' in kwargs.get("q", "")


class TestFetchDtmBytes:
    def test_reads_internal_bucket_by_asset_key(self):
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"TIFF"))}
        asset = type("A", (), {"asset_id": "job-42", "dtm_url": ""})()
        with patch("app.services.lidar_dem.get_s3_client", return_value=s3):
            data = fetch_dtm_bytes(asset)
        assert data == b"TIFF"
        s3.get_object.assert_called_once_with(
            Bucket=LIDAR_TILESETS_BUCKET, Key="job-42/dtm.tif"
        )

    def test_derives_key_from_full_urn_dtm_url(self):
        """Historical layers upload under the full job URN prefix — the key
        must come from the URL, not the short asset id."""
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"T"))}
        asset = type("A", (), {
            "asset_id": "7f490884-d517-4c2d-82d8-b09e1ed8611f",
            "dtm_url": "https://minio.robotika.cloud/lidar-tilesets/urn:ngsi-ld:DataProcessingJob:7f490884-d517-4c2d-82d8-b09e1ed8611f/dtm.tif",
        })()
        with patch("app.services.lidar_dem.get_s3_client", return_value=s3):
            fetch_dtm_bytes(asset)
        s3.get_object.assert_called_once_with(
            Bucket=LIDAR_TILESETS_BUCKET,
            Key="urn:ngsi-ld:DataProcessingJob:7f490884-d517-4c2d-82d8-b09e1ed8611f/dtm.tif",
        )


class TestLidarCellsizeGate:
    def test_small_parcel_keeps_native(self):
        from app.services.lidar_dem import lidar_target_cellsize
        assert lidar_target_cellsize(3.0) is None  # native 0.5 m

    def test_large_parcel_resampled_to_2m(self):
        from app.services.lidar_dem import lidar_target_cellsize
        assert lidar_target_cellsize(10.0) == 2.0
        assert lidar_target_cellsize(54.0) == 2.0
