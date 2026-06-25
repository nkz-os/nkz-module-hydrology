"""Tests for OrionContextClient."""
from unittest.mock import patch

from app.services.orion_context_client import (
    OrionContextClient,
    SoilContext,
    _derive_hsg,
    _hsg_to_cn,
    _derive_k_factor,
)


class TestHSGDerivation:
    def test_sand_is_a(self):
        assert _derive_hsg("sand") == "A"

    def test_clay_is_d(self):
        assert _derive_hsg("clay") == "D"

    def test_loam_is_b(self):
        assert _derive_hsg("loam") == "B"

    def test_sandy_clay_loam_is_c(self):
        assert _derive_hsg("sandy_clay_loam") == "C"

    def test_unknown_texture_defaults_to_c(self):
        assert _derive_hsg("gravel") == "C"


class TestHSGToCN:
    def test_a_row_crops_is_67(self):
        assert _hsg_to_cn("A", "row_crops") == 67

    def test_d_row_crops_is_89(self):
        assert _hsg_to_cn("D", "row_crops") == 89


class TestKFactorDerivation:
    def test_clay_has_low_k(self):
        assert _derive_k_factor("clay") < _derive_k_factor("sand")

    def test_loam_is_around_0_3(self):
        assert 0.25 <= _derive_k_factor("loam") <= 0.4

    def test_organic_matter_reduces_k(self):
        assert _derive_k_factor("loam", organic_carbon_pct=2.0) < _derive_k_factor("loam", organic_carbon_pct=0.5)


class TestOrionContextClient:
    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_get_soil_context_returns_defaults_when_no_entity(self, MockOrion):
        """query_entities returns empty list -> defaults."""
        mock_orion = MockOrion.return_value.__enter__.return_value
        mock_orion.query_entities.return_value = []

        with OrionContextClient("test-tenant") as client:
            ctx = client.get_soil_context("urn:ngsi-ld:AgriParcel:p1")

        assert ctx.cn == 80.0
        assert ctx.ksat_mmh == 15.0
        assert ctx.field_capacity_vv == 0.25
        assert ctx.wilting_point_vv == 0.10
        assert ctx.k_factor == 0.30
        assert ctx.source == "default"

    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_get_soil_context_parses_real_entity(self, MockOrion):
        """AgriSoil with clay texture -> HSG D, CN 89, low K factor."""
        mock_orion = MockOrion.return_value.__enter__.return_value
        mock_orion.query_entities.return_value = [{
            "usdaTextureClass": "clay",
            "Ksaturation": 3.0,
            "fieldCapacity": 0.35,
            "wiltingPoint": 0.18,
            "organicCarbon": 1.5,
        }]

        with OrionContextClient("test-tenant") as client:
            ctx = client.get_soil_context("urn:ngsi-ld:AgriParcel:p1")

        assert ctx.cn == 89  # D + row_crops
        assert ctx.ksat_mmh == 3.0
        assert ctx.field_capacity_vv == 0.35
        assert ctx.wilting_point_vv == 0.18
        assert ctx.k_factor < 0.30  # clay -> low K
        assert ctx.source == "orion"

    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_get_ndvi_returns_default_when_no_entity(self, MockOrion):
        """Empty list -> default 0.4."""
        mock_orion = MockOrion.return_value.__enter__.return_value
        mock_orion.query_entities.return_value = []

        with OrionContextClient("test-tenant") as client:
            ndvi, source = client.get_ndvi_mean("urn:ngsi-ld:AgriParcel:p1")

        assert ndvi == 0.4
        assert source == "default"

    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_get_ndvi_returns_real_value(self, MockOrion):
        """Latest EOProduct with NDVI -> returns meanValue."""
        mock_orion = MockOrion.return_value.__enter__.return_value
        mock_orion.query_entities.return_value = [{
            "meanValue": 0.72,
            "indexType": "NDVI",
            "dateObserved": "2026-06-20T12:00:00Z",
        }]

        with OrionContextClient("test-tenant") as client:
            ndvi, source = client.get_ndvi_mean("urn:ngsi-ld:AgriParcel:p1")

        assert ndvi == 0.72
        assert source == "orion"

    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_connection_error_returns_defaults(self, MockOrion):
        """SyncOrionClient init raises -> soft-fail to defaults."""
        MockOrion.side_effect = Exception("connection refused")

        client = OrionContextClient("test-tenant")
        ctx = client.get_soil_context("urn:ngsi-ld:AgriParcel:p1")

        assert ctx.source == "default"
        assert ctx.cn == 80.0

    @patch("app.services.orion_context_client.SyncOrionClient")
    def test_ndvi_sorted_by_date_descending(self, MockOrion):
        """Multiple EOProducts -> picks the one with latest dateObserved."""
        mock_orion = MockOrion.return_value.__enter__.return_value
        mock_orion.query_entities.return_value = [
            {"meanValue": 0.50, "indexType": "NDVI", "dateObserved": "2026-06-10T00:00:00Z"},
            {"meanValue": 0.80, "indexType": "NDVI", "dateObserved": "2026-06-20T00:00:00Z"},
            {"meanValue": 0.60, "indexType": "NDVI", "dateObserved": "2026-06-15T00:00:00Z"},
        ]

        with OrionContextClient("test-tenant") as client:
            ndvi, source = client.get_ndvi_mean("urn:ngsi-ld:AgriParcel:p1")

        assert ndvi == 0.80  # latest date wins
        assert source == "orion"
