"""Tests for GPX/KML export."""
import xml.etree.ElementTree as ET

from app.services.gpx_export import geometry_to_gpx, geometry_to_kml


class TestGPXExport:
    def test_linestring_produces_trk(self):
        geom = {"type": "LineString", "coordinates": [[0, 0, 100], [1, 1, 101], [2, 2, 102]]}
        gpx = geometry_to_gpx(geom, name="Test Keyline")
        root = ET.fromstring(gpx)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        trk = root.find("gpx:trk", ns)
        assert trk is not None
        name_el = trk.find("gpx:name", ns)
        assert name_el is not None
        assert name_el.text == "Test Keyline"

    def test_point_produces_wpt(self):
        geom = {"type": "Point", "coordinates": [10, 20, 300]}
        gpx = geometry_to_gpx(geom, name="Dam 1")
        root = ET.fromstring(gpx)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        wpt = root.find("gpx:wpt", ns)
        assert wpt is not None
        assert float(wpt.attrib["lat"]) == 20

    def test_multilinestring_produces_multiple_trkseg(self):
        geom = {
            "type": "MultiLineString",
            "coordinates": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]],
        }
        gpx = geometry_to_gpx(geom, name="Swales")
        root = ET.fromstring(gpx)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        segs = root.findall(".//gpx:trkseg", ns)
        assert len(segs) == 2


class TestKMLExport:
    def test_polygon_produces_placemark(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }
        kml = geometry_to_kml(geom, name="Pond")
        assert "<Placemark>" in kml
        assert "<name>Pond</name>" in kml
        assert "<Polygon>" in kml

    def test_point_produces_placemark(self):
        geom = {"type": "Point", "coordinates": [10, 20, 300]}
        kml = geometry_to_kml(geom, name="Check Dam")
        assert "<Point>" in kml
        assert "<coordinates>10,20,300</coordinates>" in kml
