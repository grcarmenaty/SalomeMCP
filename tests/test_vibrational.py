import math

import pytest

from salome_mcp.vibrational import (
    BETA_L,
    MATERIALS,
    beam_length_for_frequency,
    beam_modes,
    plate_modes_simply_supported,
)


def test_cantilever_first_mode_matches_closed_form():
    m = MATERIALS["structural_steel"]
    L, w, t = 1.0, 0.01, 0.01
    out = beam_modes(L, w, t, m["E"], m["rho"], end_condition="cantilever", n_modes=1)
    I = w * t ** 3 / 12.0
    A = w * t
    expected = (1.875104 ** 2) / (2 * math.pi * L ** 2) * math.sqrt(
        m["E"] * I / (m["rho"] * A)
    )
    assert out.frequencies_hz[0] == pytest.approx(expected, rel=1e-6)


def test_inverse_problem_roundtrip():
    m = MATERIALS["aluminum_6061"]
    L = beam_length_for_frequency(440.0, 0.005, 0.005, m["E"], m["rho"])
    out = beam_modes(L, 0.005, 0.005, m["E"], m["rho"], n_modes=1)
    assert out.frequencies_hz[0] == pytest.approx(440.0, rel=1e-6)


def test_simply_supported_beam_uses_pi_root():
    assert BETA_L["simply-supported"][0] == pytest.approx(math.pi)


def test_invalid_end_condition_raises():
    with pytest.raises(ValueError):
        beam_modes(1.0, 0.01, 0.01, 2e11, 7800.0, end_condition="bogus")


def test_plate_modes_sorted_and_match_formula():
    M = MATERIALS["aluminum_6061"]
    a, b, h = 0.5, 0.4, 0.005
    out = plate_modes_simply_supported(a, b, h, M["E"], M["nu"], M["rho"], 3, 3)
    fs = [f for _, _, f in out.modes]
    assert fs == sorted(fs)
    # First mode (1,1)
    D = M["E"] * h ** 3 / (12 * (1 - M["nu"] ** 2))
    expected_11 = (math.pi / 2) * math.sqrt(D / (M["rho"] * h)) * (
        (1 / a) ** 2 + (1 / b) ** 2
    )
    # Find (1,1)
    f11 = next(f for m, n, f in out.modes if m == 1 and n == 1)
    assert f11 == pytest.approx(expected_11, rel=1e-9)


def test_negative_dimensions_rejected():
    with pytest.raises(ValueError):
        beam_modes(1.0, -0.01, 0.01, 2e11, 7800.0)
    with pytest.raises(ValueError):
        plate_modes_simply_supported(0.0, 0.1, 0.005, 7e10, 0.33, 2700.0)
