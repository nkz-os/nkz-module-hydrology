"""
Daily water balance bucket model.

Continuous daily soil moisture accounting with SCS-CN runoff,
FAO-56 actual ET, and gravity drainage percolation.
"""

from typing import Optional


class BucketModel:
    """Continuous daily water balance bucket.

    Simulates soil moisture dynamics using a single-layer tipping-bucket
    approach. Accounts for runoff (SCS-CN), infiltration, actual
    evapotranspiration (limited by available water), and percolation
    (gravity drainage capped at Ksat).

    States: soil_moisture (mm), updated on each step.
    """

    def __init__(
        self,
        ksat_mmh: float,
        field_capacity_vv: float,
        wilting_point_vv: float,
        depth_mm: float = 300,
    ):
        """Initialize bucket with soil hydraulic properties.

        Args:
            ksat_mmh: Saturated hydraulic conductivity (mm/h).
            field_capacity_vv: Field capacity (volumetric, m³/m³).
            wilting_point_vv: Wilting point (volumetric, m³/m³).
            depth_mm: Soil depth (mm). Default 300 mm.
        """
        self.ksat = ksat_mmh * 24  # convert to mm/day
        self.fc = field_capacity_vv * depth_mm   # field capacity in mm
        self.wp = wilting_point_vv * depth_mm    # wilting point in mm
        self.depth = depth_mm
        self.moisture = self.fc * 0.5  # initial: 50% FC

    def step(
        self,
        precip_mm: float,
        et0_mm: float,
        kc: float = 1.0,
        cn: Optional[float] = None,
    ) -> dict:
        """Advance the bucket by one day.

        Args:
            precip_mm: Daily precipitation (mm).
            et0_mm: Daily reference evapotranspiration (mm).
            kc: Crop coefficient (dimensionless). Default 1.0.
            cn: SCS curve number for runoff estimation. If None, no
                runoff is computed.

        Returns:
            Dict with fluxes and resulting state:
                precip, eto, etc, runoff, infiltration,
                aet, percolation, moisture, saturation_pct.
        """
        etc = et0_mm * kc

        # --- Runoff via SCS-CN ---
        runoff = 0.0
        if cn is not None and precip_mm > 0.2 * (25400.0 / cn - 254):
            S = 25400.0 / cn - 254
            Ia = 0.2 * S
            if precip_mm > Ia:
                runoff = (precip_mm - Ia) ** 2 / (precip_mm - Ia + S)

        # Infiltration
        infiltr = max(0.0, precip_mm - runoff)

        # --- Actual ET (limited by available moisture) ---
        avail = max(0.0, self.moisture - self.wp)
        aet = min(etc, avail * 0.7)  # max 70 % of available

        # --- Percolation (excess above field capacity) ---
        new_moisture = self.moisture + infiltr - aet
        percolation = max(0.0, new_moisture - self.fc) * 0.3  # 30 %/day
        percolation = min(percolation, self.ksat)  # limited by Ksat

        # --- Update state ---
        self.moisture = max(self.wp, min(self.fc, new_moisture - percolation))

        aw = self.fc - self.wp
        saturation_pct = (
            (self.moisture - self.wp) / aw * 100 if aw > 0 else 0.0
        )

        return {
            "precip": precip_mm,
            "eto": et0_mm,
            "etc": etc,
            "runoff": runoff,
            "infiltration": infiltr,
            "aet": aet,
            "percolation": percolation,
            "moisture": self.moisture,
            "saturation_pct": saturation_pct,
        }

    def run_series(self, daily_data: list[dict]) -> list[dict]:
        """Run a multi-day series.

        Each dict in *daily_data* must contain ``precip`` and ``et0``
        keys; ``kc`` and ``cn`` are optional (defaults: 1.0 and None).

        Returns a list of result dicts, one per day.
        """
        results = []
        for d in daily_data:
            r = self.step(
                d["precip"],
                d["et0"],
                d.get("kc", 1.0),
                d.get("cn"),
            )
            results.append(r)
        return results
