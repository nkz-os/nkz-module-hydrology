"""
Multi-objective pond siting score (pondScore).

Combines storage efficiency, reliability, soil suitability, and earthwork
cost into a single 0‑1 suitability score for pond placement decisions.

Factors
-------
* **Storage efficiency** (0‑0.4):  annual catchment yield ÷ earthwork volume.
  Capped at 0.4 when yield/earthwork ≥ 100.
* **Reliability** (0‑0.3):  fraction of years with sufficient fill.
* **Soil suitability** (0‑0.2):  texture-based ranking (clay = best).
* **Earthwork cost** (0‑0.1):  inverse of earthwork volume, higher is cheaper.

A total score > 0.4 qualifies the site as viable.
"""

_soil_scores = {
    "clay": 1.0,
    "clay_loam": 0.85,
    "loam": 0.7,
    "sandy_loam": 0.5,
    "sand": 0.3,
}

_linable_textures = frozenset({"sand", "sandy_loam"})


def pond_score(
    catchment_yield_m3: float,
    earthwork_m3: float,
    reliability_pct: float,
    ksat_mmh: float,
    texture: str = "loam",
) -> dict:
    """Compute pondScore (0‑1) and viability for a candidate pond site.

    Parameters
    ----------
    catchment_yield_m3 : float
        Mean annual runoff volume reaching the pond (m³).
    earthwork_m3 : float
        Excavation / embankment volume required (m³).
    reliability_pct : float
        Percentage of years in which the pond is expected to fill
        sufficiently (0‑100).
    ksat_mmh : float
        Saturated hydraulic conductivity of in‑situ soil (mm/h).
    texture : str, optional
        Soil texture class (default ``"loam"``).
        Supported: ``clay``, ``clay_loam``, ``loam``, ``sandy_loam``, ``sand``.

    Returns
    -------
    dict
        ``pondScore`` (0‑1), ``isViable`` (bool), ``requiresLining`` (bool),
        and ``factors`` dict with per-component scores.

    Examples
    --------
    >>> pond_score(5000, 800, 75, 5, "clay")
    {'pondScore': 0.63, 'isViable': True, 'requiresLining': False, ...}
    """
    if earthwork_m3 <= 0 or catchment_yield_m3 <= 0:
        return {
            "pondScore": 0.0,
            "isViable": False,
            "requiresLining": False,
            "factors": {},
        }

    # Storage efficiency: yield / earthwork.  Saturated at 100:1.
    eff = catchment_yield_m3 / earthwork_m3
    eff_score = min(0.4, eff / 100.0 * 0.4)

    # Reliability: fraction of years with sufficient fill.
    rel_score = reliability_pct / 100.0 * 0.3

    # Soil suitability: texture-based.
    soil_score = _soil_scores.get(texture, 0.5) * 0.2

    # Earthwork cost: inverse volume, capped.
    cost_score = min(0.1, 10000.0 / max(earthwork_m3, 1) * 0.1)

    total = eff_score + rel_score + soil_score + cost_score
    requires_lining = texture in _linable_textures or ksat_mmh > 10

    return {
        "pondScore": round(min(1.0, total), 3),
        "isViable": total > 0.4,
        "requiresLining": requires_lining,
        "factors": {
            "efficiency": eff_score,
            "reliability": rel_score,
            "soil": soil_score,
            "cost": cost_score,
        },
    }
