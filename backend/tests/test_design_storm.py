import math

import pytest

from app.services.design_storm import (
    alternating_block_hyetograph,
    depth_fraction,
    design_storm_response,
)
from app.services.scs_cn import runoff


def test_hyetograph_sums_to_depth_and_peaks_in_middle():
    h = alternating_block_hyetograph(86.0)
    assert len(h) == 24
    assert sum(h) == pytest.approx(86.0)
    assert max(h) == h[len(h) // 2 - 1] or max(h) == h[len(h) // 2]
    assert all(b > 0 for b in h)
    # decreasing away from the peak (alternating arrangement, both sides)
    i = h.index(max(h))
    assert h[i] >= h[i - 1] and h[i] >= h[i + 1]


def test_depth_fraction_monotone_and_one_at_24h():
    ds = [0.5, 1, 2, 3, 6, 12, 18, 24]
    fs = [depth_fraction(d) for d in ds]
    assert all(0 < f <= 1 for f in fs)
    assert fs == sorted(fs) and len(set(fs)) == len(fs)
    assert depth_fraction(24.0) == pytest.approx(1.0)


def test_peak_far_below_single_block_formula():
    q, peak = design_storm_response(alternating_block_hyetograph(86.0), 70, 10.0, 0.5)
    _, single = runoff(86.0, 70, 10.0, 0.5)
    assert 0 < peak < 0.25 * single
    assert q == pytest.approx(runoff(86.0, 70)[0])


def test_response_matches_hand_case():
    hy = [10.0, 40.0, 20.0]
    cn, area_ha, tc, bh = 80.0, 50.0, 1.0, 1.0
    S = 25400 / cn - 254
    ia = 0.2 * S

    def q_of(p):
        return 0.0 if p <= ia else (p - ia) ** 2 / (p - ia + S)

    cum = [10.0, 50.0, 70.0]
    inc = [q_of(cum[0]), q_of(cum[1]) - q_of(cum[0]), q_of(cum[2]) - q_of(cum[1])]
    tp = bh / 2 + 0.6 * tc
    tb = 2.67 * tp
    a = area_ha / 100.0

    def uh(t, q):
        qp = 0.208 * a * q / tp
        if t <= 0 or t >= tb:
            return 0.0
        return qp * t / tp if t <= tp else qp * (tb - t) / (tb - tp)

    # block i starts at i*bh; the unit hydrograph is the response to block excess
    peak = max(
        sum(uh(t - i * bh, inc[i]) for i in range(3))
        for t in [k * 0.001 for k in range(0, 8000)]
    )
    q, p = design_storm_response(hy, cn, area_ha, tc, bh)
    assert q == pytest.approx(q_of(70.0))
    assert p == pytest.approx(peak, rel=0.01)


def test_runoff_equals_cn_on_total_depth():
    hy = alternating_block_hyetograph(120.0)
    q, _ = design_storm_response(hy, 75, 25.0, 2.0)
    assert q == pytest.approx(runoff(120.0, 75)[0])
