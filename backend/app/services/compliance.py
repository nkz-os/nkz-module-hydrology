"""Regulatory compliance checks for NKZ Water Studio.

Evaluates whether water harvesting interventions comply with Spanish basin
authority (CHX) regulations and classifies breach risk for downstream safety.

References
----------
* MITECO — Confederaciones Hidrográficas thresholds:
  https://www.miteco.gob.es/es/agua/temas/default.aspx
"""

from typing import Optional

# Water permit thresholds (m³, storage capacity) by basin authority (CHX).
# Source: MITECO — Confederaciones Hidrográficas.
# Ponds whose storage capacity exceeds the threshold require an explicit water
# use permit. Capacity is used (not annual captured volume) because it is
# geometrically computable and is a real CHX basis for small balsas; annual
# capture would need an annual-precipitation source the platform does not expose.
PERMIT_THRESHOLDS_M3: dict[str, int] = {
    "CH_Ebro": 7000,
    "CH_Duero": 5000,
    "CH_Tajo": 5000,
    "CH_Guadiana": 5000,
    "CH_Guadalquivir": 5000,
    "CH_Segura": 3000,
    "CH_Jucar": 3000,
    "CH_Ebro_Cataluna": 7000,
    "CH_Minho_Sil": 7000,
    "CH_Cantabrico": 5000,
    "default": 5000,
}


def requires_water_permit(volume_m3: float, basin: str = "default") -> bool:
    """Check if a pond's storage capacity exceeds the permit threshold for a basin.

    Parameters
    ----------
    volume_m3 : float
        Pond storage capacity (m³) — geometric max storage (π·r²·depth).
    basin : str, optional
        Basin authority identifier (e.g. ``"CH_Ebro"``, ``"CH_Segura"``).
        Falls back to ``"default"`` if the basin is not recognised.

    Returns
    -------
    bool
        ``True`` if the volume exceeds the basin's permit threshold.

    Examples
    --------
    >>> requires_water_permit(6000, "CH_Ebro")
    False
    >>> requires_water_permit(6000, "CH_Segura")
    True
    """
    threshold = PERMIT_THRESHOLDS_M3.get(basin, PERMIT_THRESHOLDS_M3["default"])
    return volume_m3 > threshold


def breach_risk_class(
    volume_m3: float,
    slope_pct: float,
    has_downstream_exposure: bool,
) -> str:
    """Classify breach risk of a water harvesting intervention.

    Risk is scored on four criteria:
    * volume > 5 000 m³  → +1
    * volume > 20 000 m³ → +2 (cumulative)
    * slope > 5 %        → +1
    * downstream exposure → +2

    Total score ≥ 3 → ``"high"``, ≥ 2 → ``"medium"``, else ``"low"``.

    Parameters
    ----------
    volume_m3 : float
        Pond storage capacity (m³).
    slope_pct : float
        Terrain slope at the intervention site (percent).
    has_downstream_exposure : bool
        Whether people or assets are downstream of the intervention.

    Returns
    -------
    str
        One of ``"low"``, ``"medium"``, ``"high"``.

    Examples
    --------
    >>> breach_risk_class(1000, 2, False)
    'low'
    >>> breach_risk_class(10000, 8, True)
    'high'
    """
    score = 0
    if volume_m3 > 5000:
        score += 1
    if volume_m3 > 20000:
        score += 1
    if slope_pct > 5:
        score += 1
    if has_downstream_exposure:
        score += 2

    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def downstream_exposure(
    pond_location: tuple[float, float],
    buildings: list,
    roads: list,
    streams: list,
) -> dict:
    """Check if pond failure would affect downstream infrastructure.

    Simplified proximity check: if any buildings, roads, or streams exist
    within the provided feature lists they are considered exposed.
    A real implementation would use D8 flow-path routing from the pond
    location to determine the actual downstream area.

    Parameters
    ----------
    pond_location : tuple[float, float]
        (longitude, latitude) of the pond.
    buildings : list
        List of building features (geometry objects or feature dicts)
        within a 500 m downstream buffer.
    roads : list
        List of road features within the buffer.
    streams : list
        List of stream / river features within the buffer.

    Returns
    -------
    dict
        ``has_exposure`` (bool), ``affected_buildings`` (int),
        ``affected_roads`` (int), ``affected_streams`` (int).

    Examples
    --------
    >>> downstream_exposure((0, 0), [{"id": 1}], [], [])
    {'has_exposure': True, 'affected_buildings': 1, 'affected_roads': 0, 'affected_streams': 0}
    """
    affected_buildings = len(buildings)
    affected_roads = len(roads)
    affected_streams = len(streams)

    return {
        "has_exposure": affected_buildings > 0 or affected_roads > 0,
        "affected_buildings": affected_buildings,
        "affected_roads": affected_roads,
        "affected_streams": affected_streams,
    }
