"""Scenario engine for NKZ Water Studio.

Compares baseline vs intervention KPIs to evaluate the impact of water
harvesting interventions (ponds, keylines, terraces) on a parcel.

Components
----------
* ``ScenarioKPI`` — dataclass holding water, sediment, cost, and reliability metrics.
* ``simulate_baseline`` — reference scenario with no interventions.
* ``simulate_intervention`` — scenario with capture, retention, earthwork, and cost.
* ``compare_scenarios`` — sorted comparison table from a dict of named scenarios.
"""

from dataclasses import dataclass


@dataclass
class ScenarioKPI:
    """Key Performance Indicators for a water harvesting scenario.

    Attributes
    ----------
    water_captured_m3 : float
        Volume of runoff captured by interventions (m³).
    runoff_avoided_m3 : float
        Volume of runoff that no longer leaves the parcel (m³).
    sediment_retained_t : float
        Sediment retained by interventions (tonnes).
    earthwork_m3 : float
        Excavation / embankment volume required (m³).
    investment_eur : float
        Total investment cost (€).
    water_autonomy_pct : float
        Fraction of irrigation demand met by captured water (0‑100 %).
    reliability_pct : float
        Fraction of years with sufficient water supply (0‑100 %).
    """
    water_captured_m3: float = 0
    runoff_avoided_m3: float = 0
    sediment_retained_t: float = 0
    earthwork_m3: float = 0
    investment_eur: float = 0
    water_autonomy_pct: float = 0
    reliability_pct: float = 0


def simulate_baseline(
    annual_runoff_m3: float,
    annual_sediment_t: float,
    annual_et_m3: float,
    annual_precip_m3: float,
) -> ScenarioKPI:
    """Baseline scenario: no interventions, only natural fluxes.

    Parameters
    ----------
    annual_runoff_m3 : float
        Mean annual runoff volume leaving the parcel (m³).
    annual_sediment_t : float
        Mean annual sediment loss (tonnes).
    annual_et_m3 : float
        Mean annual evapotranspiration (m³).
    annual_precip_m3 : float
        Mean annual precipitation volume on the parcel (m³).

    Returns
    -------
    ScenarioKPI
        Baseline KPI with zero capture and retention.
    """
    return ScenarioKPI(
        water_captured_m3=0,
        runoff_avoided_m3=0,
        sediment_retained_t=0,
    )


def simulate_intervention(
    baseline: ScenarioKPI,
    runoff_captured_m3: float,
    sediment_retained_t: float,
    earthwork_m3: float,
    cost_per_m3: float = 8.0,
    irrigation_demand_m3: float = 0,
) -> ScenarioKPI:
    """Intervention scenario: capture + retention + earthwork costs.

    Parameters
    ----------
    baseline : ScenarioKPI
        Baseline scenario for reference (reliability is carried forward).
    runoff_captured_m3 : float
        Volume of runoff captured by the intervention (m³).
    sediment_retained_t : float
        Sediment retained by the intervention (tonnes).
    earthwork_m3 : float
        Excavation / embankment volume required (m³).
    cost_per_m3 : float, optional
        Unit cost of earthwork (€/m³, default 8.0).
    irrigation_demand_m3 : float, optional
        Annual irrigation water demand (m³).  Used to compute autonomy.

    Returns
    -------
    ScenarioKPI
        Intervention KPI with capture, avoided runoff, retained sediment,
        earthwork volume, investment cost, and water autonomy.

    Examples
    --------
    >>> bl = simulate_baseline(10000, 50, 2000, 5000)
    >>> iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=8000)
    >>> iv.water_captured_m3
    6000
    >>> iv.water_autonomy_pct
    75.0
    """
    # Water autonomy only makes sense when there is demand.
    if irrigation_demand_m3 > 0:
        autonomy = min(100, runoff_captured_m3 / irrigation_demand_m3 * 100)
    else:
        autonomy = 0.0

    return ScenarioKPI(
        water_captured_m3=runoff_captured_m3,
        runoff_avoided_m3=runoff_captured_m3,
        sediment_retained_t=sediment_retained_t,
        earthwork_m3=earthwork_m3,
        investment_eur=earthwork_m3 * cost_per_m3,
        water_autonomy_pct=autonomy,
        reliability_pct=baseline.reliability_pct,
    )


def compare_scenarios(scenarios: dict[str, ScenarioKPI]) -> list[dict]:
    """Return sorted comparison table from a dict of named scenarios.

    Parameters
    ----------
    scenarios : dict[str, ScenarioKPI]
        Mapping of scenario names to their KPI objects.

    Returns
    -------
    list[dict]
        List of dicts, each containing ``name`` and all KPI fields, sorted
        alphabetically by name.  Suitable for JSON serialisation or tabular
        display.

    Examples
    --------
    >>> bl = simulate_baseline(10000, 50, 2000, 5000)
    >>> iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=8000)
    >>> compare_scenarios({"Baseline": bl, "Intervention": iv})
    [{'name': 'Baseline', 'water_captured_m3': 0, ...},
     {'name': 'Intervention', 'water_captured_m3': 6000, ...}]
    """
    return sorted(
        ({"name": name, **vars(kpi)} for name, kpi in scenarios.items()),
        key=lambda row: row["name"],
    )
