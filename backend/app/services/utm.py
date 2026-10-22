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
from affine import Affine
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
    cellsize_m: float | None = None,
) -> bytes:
    """Reproject a GeoTIFF in degrees (EPSG:4258/4326) to UTM (metric cellsize).

    Also accepts metric inputs (e.g. LiDAR DTM in EPSG:25830) — the source
    CRS is read from the file.  ``cellsize_m`` optionally forces the output
    cell size (used to resample 0.5 m LiDAR DTMs up on large parcels so the
    flow-accumulation engine stays within sane memory bounds).

    Args:
        geotiff_degrees: Input GeoTIFF bytes (any CRS readable by rasterio).
        centroid_lon/lat: Centroid used to pick the UTM zone.
        cellsize_m: Force output cell size (meters). None keeps native.

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
        if cellsize_m is not None and cellsize_m > 0:
            # Rescale the default transform to the requested cell size.
            scale_x = abs(transform.a) / cellsize_m
            scale_y = abs(transform.e) / cellsize_m
            transform = Affine(cellsize_m, 0.0, transform.c, 0.0, -cellsize_m, transform.f)
            width = max(1, round(width * scale_x))
            height = max(1, round(height * scale_y))
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
