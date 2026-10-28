"""Design-storm hyetograph and peak flow through the SCS unit hydrograph.

A 24-h depth is distributed with the alternating-block method and each block's
excess (from the cumulative SCS-CN curve) is routed through the SCS triangular
unit hydrograph and superposed. This replaces the single-block peak
``0.208*A*Q/Tc``, which treats the whole storm as one burst of duration Tc.
"""
from __future__ import annotations

from app.services.scs_cn import runoff

# Ratio of the 1-h to the mean-daily rainfall intensity (I1/Id).
# ASSUMPTION: 11 is a representative value for the Spanish mainland; make it a
# parameter of depth_fraction when a regional map is wired in.
DEFAULT_I1_ID = 11.0


def depth_fraction(duration_h: float, i1_id: float = DEFAULT_I1_ID) -> float:
    """Fraction of the 24-h depth that falls in the most intense ``duration_h``.

    Intensity-duration relation of the Spanish road drainage standard
    (Ministerio de Fomento, Norma 5.2-IC "Drenaje superficial", Temez 1978):

        I_t / I_d = (I_1 / I_d) ** ((28**0.1 - t**0.1) / (28**0.1 - 1))

    with I_d the mean daily intensity. Depth P_t = I_t * t is normalised by the
    value at 24 h so that f(24) = 1 exactly. Monotone increasing in t for
    I_1/I_d up to about 15.
    """
    if duration_h <= 0:
        return 0.0
    if duration_h >= 24.0:
        return 1.0

    def depth(t: float) -> float:
        e = (28.0**0.1 - t**0.1) / (28.0**0.1 - 1.0)
        return t * i1_id**e

    return depth(duration_h) / depth(24.0)


def alternating_block_hyetograph(depth_24h_mm: float, block_h: float = 1.0) -> list[float]:
    """24/block_h block depths (mm), summing to ``depth_24h_mm``, largest in the middle."""
    n = int(round(24.0 / block_h))
    cum = [depth_fraction(block_h * (k + 1)) * depth_24h_mm for k in range(n)]
    cum[-1] = depth_24h_mm
    incs = [cum[0]] + [cum[k] - cum[k - 1] for k in range(1, n)]  # descending
    out: list[float] = [0.0] * n
    centre = n // 2 - 1 if n % 2 == 0 else n // 2
    # order of positions: centre, right, left, right, left, ...
    positions = [centre]
    for step in range(1, n):
        off = (step + 1) // 2
        pos = centre + off if step % 2 == 1 else centre - off
        positions.append(pos)
    # even n: the left side is one block shorter; fold any overflow to the right end
    free = [p for p in range(n) if p not in positions]
    positions = [p for p in positions if 0 <= p < n]
    positions += free
    for p, v in zip(positions, incs):
        out[p] = v
    return out


def design_storm_response(
    hyetograph_mm: list[float],
    cn: float,
    area_ha: float,
    tc_h: float,
    block_h: float = 1.0,
) -> tuple[float, float]:
    """Return ``(runoff_mm, peak_m3s)`` for the storm.

    Excess per block = increment of cumulative SCS-CN runoff. Each block gives a
    triangular hydrograph with Tp = block_h/2 + 0.6*tc, qp = 0.208*A_km2*Q/Tp,
    base 2.67*Tp; the hydrographs are superposed and the maximum returned.
    """
    area_km2 = area_ha / 100.0
    tp = block_h / 2.0 + 0.6 * tc_h
    tb = 2.67 * tp

    excess: list[float] = []
    cum_p = 0.0
    prev_q = 0.0
    for p in hyetograph_mm:
        cum_p += p
        q = runoff(cum_p, cn)[0]
        excess.append(q - prev_q)
        prev_q = q

    pulses = [(i * block_h, 0.208 * area_km2 * e / tp) for i, e in enumerate(excess) if e > 0]

    def flow(t: float) -> float:
        total = 0.0
        for t0, qp in pulses:
            x = t - t0
            if x <= 0 or x >= tb:
                continue
            total += qp * x / tp if x <= tp else qp * (tb - x) / (tb - tp)
        return total

    # piecewise linear: the maximum is at a breakpoint
    times = {t0 + d for t0, _ in pulses for d in (0.0, tp, tb)}
    peak = max((flow(t) for t in times), default=0.0)
    return prev_q, peak
