"""
Modified Universal Soil Loss Equation (MUSLE) for event sediment yield.

MUSLE replaces the rainfall-energy factor in USLE with a runoff-energy
factor, making it suitable for individual storm-event sediment yield
predictions rather than long-term annual averages.

References
----------
Williams, J. R. (1975). Sediment routing for agricultural watersheds.
    Journal of the Water Resources Planning and Management Division, 101(1), 65–76.
Wischmeier, W. H. & Smith, D. D. (1978). Predicting rainfall erosion losses.
    USDA Agriculture Handbook No. 537.
"""

import math


def musle_sediment(
    runoff_m3: float,
    peak_flow_m3s: float,
    k_factor: float,
    ls_factor: float,
    c_factor: float,
    p_factor: float = 1.0,
) -> float:
    """Event sediment yield (tonnes) using the MUSLE formula.

    ``Y = 11.8 × (Q × qp)^0.56 × K × LS × C × P``

    where *Q* is the runoff volume (acre-ft) and *qp* is the peak
    flow rate (ft³/s).  Inputs and outputs are metric.

    Parameters
    ----------
    runoff_m3 : float
        Event runoff volume (m³).
    peak_flow_m3s : float
        Peak runoff discharge (m³/s).
    k_factor : float
        Soil erodibility factor (dimensionless, 0‑1).
    ls_factor : float
        Slope length‑steepness factor (dimensionless).
    c_factor : float
        Cover‑management factor (dimensionless, 0‑1).
    p_factor : float, optional
        Support practice factor (dimensionless, 0‑1, default 1.0).

    Returns
    -------
    float
        Sediment yield in tonnes.  Zero when runoff or peak flow is
        non‑positive.
    """
    # Convert metric inputs to the imperial units expected by MUSLE
    Q_acre_ft = runoff_m3 / 1233.48
    qp_cfs = peak_flow_m3s / 0.0283168

    if Q_acre_ft <= 0 or qp_cfs <= 0:
        return 0.0

    energy = (Q_acre_ft * qp_cfs) ** 0.56
    return 11.8 * energy * k_factor * ls_factor * c_factor * p_factor


def ls_from_slope(slope_pct: float, slope_length_m: float = 50.0) -> float:
    """Wischmeier‑Smith LS factor from slope and slope length.

    The length exponent *m* varies with slope steepness:

    * ``m = 0.5`` for slope >= 5 %
    * ``m = 0.4`` for 3 % <= slope < 5 %
    * ``m = 0.3`` for slope < 3 %

    Parameters
    ----------
    slope_pct : float
        Slope steepness in percent.
    slope_length_m : float, optional
        Slope length in metres (default 50 m).

    Returns
    -------
    float
        LS factor (dimensionless).
    """
    s = slope_pct / 100.0

    if slope_pct >= 5:
        m = 0.5
    elif slope_pct >= 3:
        m = 0.4
    else:
        m = 0.3

    L = (slope_length_m / 22.13) ** m
    S = (65.41 * s**2 + 4.56 * s + 0.065) / (s**2 + 2.24 * s + 0.065)
    return L * S


def c_from_ndvi(ndvi: float) -> float:
    """Cover‑management factor estimated from NDVI (Choudhury approx.).

    ``C = max(0.01, min(1.0, 1 − (NDVI − 0.1) / (0.8 − 0.1)))``

    Clamped to [0.01, 1.0].

    Parameters
    ----------
    ndvi : float
        Normalised Difference Vegetation Index (typically −1 to 1).

    Returns
    -------
    float
        C factor in [0.01, 1.0].
    """
    return max(0.01, min(1.0, 1.0 - (ndvi - 0.1) / (0.8 - 0.1)))
