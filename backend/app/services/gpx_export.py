"""GPX 1.1 and KML 2.2 export helpers.

Converts GeoJSON geometry dicts to GPX (waypoints + tracks) and KML
(Placemarks). Lat/Lon is expected in WGS84 (EPSG:4326). The caller
is responsible for reprojecting from UTM if needed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

GPX_NS = "http://www.topografix.com/GPX/1/1"
KML_NS = "http://www.opengis.net/kml/2.2"


def geometry_to_gpx(geometry: dict[str, Any], name: str = "Hydrology Design") -> str:
    """Convert a GeoJSON geometry to GPX 1.1 XML string."""
    gpx = ET.Element("gpx", version="1.1", creator="NKZ Water Studio",
                     xmlns=GPX_NS)
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if gtype == "Point":
        x, y = coords[0], coords[1]
        z = coords[2] if len(coords) > 2 else 0
        wpt = ET.SubElement(gpx, "wpt", lat=str(y), lon=str(x))
        ET.SubElement(wpt, "name").text = name
        ET.SubElement(wpt, "ele").text = str(z)

    elif gtype in ("LineString", "MultiLineString"):
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = name
        if gtype == "LineString":
            coords_list = [coords]
        else:
            coords_list = coords
        for seg_coords in coords_list:
            trkseg = ET.SubElement(trk, "trkseg")
            for pt in seg_coords:
                trkpt = ET.SubElement(trkseg, "trkpt",
                                      lat=str(pt[1]), lon=str(pt[0]))
                if len(pt) > 2:
                    ET.SubElement(trkpt, "ele").text = str(pt[2])

    elif gtype == "MultiPoint":
        for pt in coords:
            x, y = pt[0], pt[1]
            z = pt[2] if len(pt) > 2 else 0
            wpt = ET.SubElement(gpx, "wpt", lat=str(y), lon=str(x))
            ET.SubElement(wpt, "ele").text = str(z)

    ET.indent(gpx, space="  ")
    return ET.tostring(gpx, encoding="unicode",
                       xml_declaration=True)


def geometry_to_kml(geometry: dict[str, Any], name: str = "Hydrology Design") -> str:
    """Convert a GeoJSON geometry to KML 2.2 XML string."""
    kml = ET.Element("kml", xmlns=KML_NS)
    doc = ET.SubElement(kml, "Document")
    placemark = ET.SubElement(doc, "Placemark")
    ET.SubElement(placemark, "name").text = name

    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    coord_str = _geojson_coords_to_kml(coords, gtype)

    if gtype == "Point":
        ET.SubElement(placemark, "Point").append(
            ET.Element("coordinates")
        )
        placemark.find("Point/coordinates").text = coord_str
    elif gtype == "LineString":
        ET.SubElement(placemark, "LineString").append(
            ET.Element("coordinates")
        )
        placemark.find("LineString/coordinates").text = coord_str
    elif gtype == "Polygon":
        outer = ET.SubElement(placemark, "Polygon")
        outer_bound = ET.SubElement(outer, "outerBoundaryIs")
        ET.SubElement(outer_bound, "LinearRing").append(
            ET.Element("coordinates")
        )
        outer_bound.find("LinearRing/coordinates").text = coord_str
    elif gtype == "MultiLineString":
        multi = ET.SubElement(placemark, "MultiGeometry")
        for seg_coords in coords:
            line = ET.SubElement(multi, "LineString")
            ET.SubElement(line, "coordinates").text = _coords_list_to_kml(seg_coords)
    elif gtype == "MultiPoint":
        for pt in coords:
            pm = ET.SubElement(doc, "Placemark")
            pm.append(ET.Element("Point"))
            pm.find("Point").append(ET.Element("coordinates"))
            pt_str = f"{pt[0]},{pt[1]}"
            if len(pt) > 2:
                pt_str += f",{pt[2]}"
            pm.find("Point/coordinates").text = pt_str

    ET.indent(kml, space="  ")
    return ET.tostring(kml, encoding="unicode",
                       xml_declaration=True)


def _geojson_coords_to_kml(coords: Any, gtype: str) -> str:
    if gtype == "Point":
        return f"{coords[0]},{coords[1]},{coords[2] if len(coords) > 2 else 0}"
    elif gtype in ("LineString", "Polygon"):
        return _coords_list_to_kml(coords[0] if gtype == "Polygon" else coords)
    return ""


def _coords_list_to_kml(coords: list) -> str:
    return " ".join(
        f"{pt[0]},{pt[1]},{pt[2] if len(pt) > 2 else 0}"
        for pt in coords
    )
