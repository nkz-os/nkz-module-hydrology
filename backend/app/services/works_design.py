"""
Works design helpers for water-harvesting structures.

Provides quick-sizing calculations for swales, check dams, and sediment
retention — intended for early‑stage feasibility checks, not detailed
engineering design.
"""


def swale_capacity(
    ksat_mmh: float,
    wetted_perimeter_m: float,
    length_m: float,
    fill_time_h: float = 24,
) -> dict:
    """Infiltration capacity of a swale during a design storm.

    The swale is modeled as a rectangular infiltration basin: the volume
    captured is the infiltration rate multiplied by the fill time.

    Parameters
    ----------
    ksat_mmh : float
        Saturated hydraulic conductivity of the swale bottom (mm/h).
    wetted_perimeter_m : float
        Wetted perimeter of the swale cross‑section (m).
    length_m : float
        Swale length along the contour (m).
    fill_time_h : float, optional
        Design storm duration (hours, default 24).

    Returns
    -------
    dict
        ``volume_m3`` — total infiltration volume (m³).
        ``infilt_rate_m3h`` — steady‑state infiltration rate (m³/h).
    """
    infilt_rate = ksat_mmh * wetted_perimeter_m * length_m / 1000.0  # m³/h
    volume = infilt_rate * fill_time_h
    return {
        "volume_m3": volume,
        "infilt_rate_m3h": infilt_rate,
    }


def check_dam_spacing(channel_slope: float, dam_height_m: float) -> float:
    """Recommended check‑dam spacing by the crest‑to‑toe rule.

    ``spacing = dam_height / channel_slope``

    Parameters
    ----------
    channel_slope : float
        Channel slope (m/m, e.g. 0.05 for 5 %).
    dam_height_m : float
        Check‑dam height above the channel bed (m).

    Returns
    -------
    float
        Crest‑to‑next‑toe spacing in metres.  Zero when slope is
        non‑positive.
    """
    if channel_slope <= 0:
        return 0.0
    return dam_height_m / channel_slope


def check_dam_sediment_retention(
    dam_height_m: float,
    width_m: float,
    bulk_density_tm3: float = 1.3,
) -> float:
    """Sediment mass retained behind a check dam (tonnes).

    The retained volume is approximated as a triangular prism whose
    cross‑section is a right triangle with legs *height* and *height*,
    projected across the dam width:

    ``volume = height² × width / 2``

    This is a conservative first‑order estimate assuming the dam fills
    to crest height with a flat sediment surface.

    Parameters
    ----------
    dam_height_m : float
        Effective dam height above the original bed (m).
    width_m : float
        Dam width across the channel (m).
    bulk_density_tm3 : float, optional
        Bulk density of trapped sediment (t/m³, default 1.3).

    Returns
    -------
    float
        Sediment mass in tonnes.
    """
    volume_m3 = dam_height_m**2 * width_m / 2.0
    return volume_m3 * bulk_density_tm3
