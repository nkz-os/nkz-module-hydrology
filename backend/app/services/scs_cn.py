"""
SCS Curve Number runoff estimation.

Implements the USDA-NRCS Curve Number method for direct runoff
from rainfall, with adjustments for Antecedent Moisture Condition
and tabulated CN values for common land-use / HSG combinations.
"""

# Curve Number for Hydrologic Soil Group × land use
# HSG: A (low runoff) → D (high runoff)
# AMC II (normal antecedent moisture)
HSG_CN_TABLE: dict[tuple[str, str], int] = {
    ("A", "row_crops"): 67,
    ("B", "row_crops"): 78,
    ("C", "row_crops"): 85,
    ("D", "row_crops"): 89,
    ("A", "pasture"): 49,
    ("B", "pasture"): 69,
    ("C", "pasture"): 79,
    ("D", "pasture"): 84,
    ("A", "forest"): 30,
    ("B", "forest"): 55,
    ("C", "forest"): 70,
    ("D", "forest"): 77,
}


def cn_for_amc(cn2: float, amc: str) -> float:
    """Adjust curve number for Antecedent Moisture Condition.

    Args:
        cn2: Curve number for AMC II (normal conditions).
        amc: Moisture condition — ``"I"`` (dry), ``"II"`` (normal),
            or ``"III"`` (wet).

    Returns:
        Adjusted curve number.
    """
    if amc == "I":
        return cn2 / (2.281 - 0.01281 * cn2)
    elif amc == "III":
        return cn2 / (0.427 + 0.00573 * cn2)
    # AMC II — no adjustment
    return cn2


def runoff(precip_mm: float, cn: float, area_ha: float = 100.0, tc_h: float = 0.5) -> tuple[float, float]:
    """Compute SCS-CN direct runoff and peak flow.

    Args:
        precip_mm: Rainfall depth (mm).
        cn: Curve number (adjusted for AMC if needed).
        area_ha: Drainage area in hectares (default 100 ha = 1 km²).
        tc_h: Time of concentration in hours (default 0.5).

    Returns:
        Tuple of (runoff_mm, peak_flow_m3s). Peak flow uses
        the SCS triangular unit hydrograph:
        qp = (0.208 * A_km² * Q_mm) / Tc_h
    """
    S = 25400.0 / cn - 254
    Ia = 0.2 * S
    if precip_mm <= Ia:
        return (0.0, 0.0)

    Q = (precip_mm - Ia) ** 2 / (precip_mm - Ia + S)
    # SCS peak flow formula expects A in km² (not ha).
    # Constant 0.208 = (2 * 1e6) / (3600 * 1000 * …) for SI units:
    # Qp (m³/s) = 0.208 * A(km²) * Q(mm) / Tp(h)
    area_km2 = area_ha / 100.0
    qp = (0.208 * Q * area_km2) / tc_h
    return (Q, qp)
