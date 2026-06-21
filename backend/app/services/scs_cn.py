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


def runoff(precip_mm: float, cn: float) -> tuple[float, float]:
    """Compute SCS-CN direct runoff and simplified peak flow.

    Args:
        precip_mm: Rainfall depth (mm).
        cn: Curve number (adjusted for AMC if needed).

    Returns:
        Tuple of (runoff_mm, peak_flow_m3s).
    """
    S = 25400.0 / cn - 254
    Ia = 0.2 * S
    if precip_mm <= Ia:
        return (0.0, 0.0)

    Q = (precip_mm - Ia) ** 2 / (precip_mm - Ia + S)
    # Simplified peak flow (m³/s) per unit area (km² → 100 ha)
    qp = 0.208 * Q * 100.0 / 0.5
    return (Q, qp)
