"""UTM zone derivation + EPSG:4258 grid -> UTM reprojection.

The geolibre engine reads the cellsize from the GeoTIFF geotransform and needs
metres. EPSG:4258 grids (degrees) must be reprojected to UTM before the engine.
This is the CRS trap #1 defense (spec §3.4).
"""
from __future__ import annotations

import io
import math

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling


def utm_zone_from_centroid(lon: float, lat: float) -> int:
    """UTM zone number for a longitude (1..60). Spain is zones 28-31."""
    return int(math.floor((lon + 180.0) / 6.0) + 1)


def utm_epsg_from_centroid(lon: float, lat: float) -> str:
    """ETRS89 UTM EPSG code for the centroid (Northern hemisphere assumed for Spain)."""
    zone = utm_zone_from_centroid(lon, lat)
    if lat >= 0:
        return f"EPSG:258{zone:02d}"   # ETRS89 / UTM zone N
    return f"EPSG:327{zone:02d}"       # WGS84 / UTM zone S (not used for Spain)


def reproject_grid_to_utm(
    geotiff_degrees: bytes,
    centroid_lon: float,
    centroid_lat: float,
) -> bytes:
    """Reproject a GeoTIFF in degrees (EPSG:4258/4326) to UTM (metric cellsize).

    Args:
        geotiff_degrees: Input GeoTIFF bytes in a geographic CRS.
        centroid_lon/lat: Centroid used to pick the UTM zone.

    Returns:
        GeoTIFF bytes reprojected to ETRS89 UTM, with metric cellsize.
    """
    dst_crs = utm_epsg_from_centroid(centroid_lon, centroid_lat)
    src = io.BytesIO(geotiff_degrees)
    with rasterio.open(src) as ds:
        src_transform = ds.transform
        src_crs = ds.crs
        src_nodata = ds.nodata

        transform, width, height = calculate_default_transform(
            src_crs, dst_crs, ds.width, ds.height, *ds.bounds
        )
        fill = src_nodata if src_nodata is not None else -9999.0
        profile = ds.profile.copy()
        profile.update(
            crs=dst_crs, transform=transform, width=width, height=height,
            nodata=fill,  # declare fill as nodata so borders are maskable downstream
        )

        dst = np.full((height, width), fill, dtype="float32")
        reproject(
            source=rasterio.band(ds, 1),
            destination=dst,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=src_nodata,
            dst_nodata=fill,
        )

    out = io.BytesIO()
    with rasterio.open(out, "w", **profile) as dst_ds:
        dst_ds.write(dst.astype("float32"), 1)
    return out.getvalue()
