"""Analytical helpers that translate vibrational targets into geometry hints.

Two closed-form workhorses cover most resonator design questions a model is
likely to encounter:

* Euler-Bernoulli bending of slender prismatic beams
  (cantilever, fixed-fixed, simply supported, free-free).
* Kirchhoff-Love thin rectangular plate, simply supported on all edges.

These help the model translate prompts like "ring at 440 Hz" or
"first mode below 50 Hz" into concrete dimensions before it issues
geometry-construction tool calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# β_n L roots for Euler-Bernoulli bending, by end condition.
BETA_L: dict[str, list[float]] = {
    "cantilever":         [1.875104, 4.694091, 7.854757, 10.995541, 14.137168],
    "fixed-fixed":        [4.730041, 7.853205, 10.995608, 14.137166, 17.278759],
    "simply-supported":   [math.pi, 2 * math.pi, 3 * math.pi, 4 * math.pi, 5 * math.pi],
    "free-free":          [4.730041, 7.853205, 10.995608, 14.137166, 17.278759],
}

# Common engineering materials (SI units: Pa, dimensionless, kg/m^3).
MATERIALS: dict[str, dict[str, float]] = {
    "structural_steel": {"E": 2.10e11, "nu": 0.30, "rho": 7850.0},
    "stainless_316":    {"E": 1.93e11, "nu": 0.30, "rho": 8000.0},
    "aluminum_6061":    {"E": 6.89e10, "nu": 0.33, "rho": 2700.0},
    "titanium_grade5":  {"E": 1.14e11, "nu": 0.34, "rho": 4430.0},
    "brass":            {"E": 1.10e11, "nu": 0.34, "rho": 8500.0},
    "copper":           {"E": 1.17e11, "nu": 0.34, "rho": 8960.0},
    "abs_plastic":      {"E": 2.30e9,  "nu": 0.35, "rho": 1040.0},
    "pla_plastic":      {"E": 3.50e9,  "nu": 0.36, "rho": 1240.0},
    "concrete":         {"E": 3.00e10, "nu": 0.20, "rho": 2400.0},
    "glass_borosilicate": {"E": 6.40e10, "nu": 0.20, "rho": 2230.0},
    "oak_wood":         {"E": 1.10e10, "nu": 0.30, "rho": 750.0},
}


@dataclass
class BeamModes:
    end_condition: str
    frequencies_hz: list[float]
    bending_axis: str
    second_moment_m4: float


def _section(
    width: float, thickness: float
) -> tuple[float, float, float, str, float]:
    """Return (b, h, I_min, axis, A) where bending is about the small-I axis."""
    if width <= 0 or thickness <= 0:
        raise ValueError("width and thickness must be positive.")
    h, b = sorted([width, thickness])  # h is the smaller dimension
    I = b * h ** 3 / 12.0
    A = b * h
    axis = "thickness" if h == thickness else "width"
    return b, h, I, axis, A


def beam_modes(
    length: float,
    width: float,
    thickness: float,
    E: float,
    rho: float,
    end_condition: str = "cantilever",
    n_modes: int = 5,
) -> BeamModes:
    """Euler-Bernoulli bending modes of a slender prismatic beam.

    f_n = (β_n L)^2 / (2π L^2) · sqrt(E I / (ρ A))
    Bending occurs about the smaller-I axis (out-of-plane direction).
    """
    if length <= 0:
        raise ValueError("length must be positive.")
    if end_condition not in BETA_L:
        raise ValueError(
            f"Unknown end_condition '{end_condition}'. "
            f"Choose one of: {sorted(BETA_L)}"
        )
    if n_modes < 1 or n_modes > len(BETA_L[end_condition]):
        raise ValueError(f"n_modes must be in 1..{len(BETA_L[end_condition])}")
    b, h, I, axis, A = _section(width, thickness)
    pre = math.sqrt(E * I / (rho * A)) / (2.0 * math.pi * length ** 2)
    freqs = [pre * (bl ** 2) for bl in BETA_L[end_condition][:n_modes]]
    return BeamModes(
        end_condition=end_condition,
        frequencies_hz=freqs,
        bending_axis=axis,
        second_moment_m4=I,
    )


def beam_length_for_frequency(
    target_hz: float,
    width: float,
    thickness: float,
    E: float,
    rho: float,
    mode: int = 1,
    end_condition: str = "cantilever",
) -> float:
    """Beam length L that places the n-th bending mode at ``target_hz``."""
    if target_hz <= 0:
        raise ValueError("target_hz must be positive.")
    if end_condition not in BETA_L:
        raise ValueError(f"Unknown end_condition '{end_condition}'.")
    n_max = len(BETA_L[end_condition])
    if mode < 1 or mode > n_max:
        raise ValueError(f"mode must be in 1..{n_max}")
    bL = BETA_L[end_condition][mode - 1]
    b, h, I, _axis, A = _section(width, thickness)
    L_sq = (bL ** 2) / (2.0 * math.pi * target_hz) * math.sqrt(E * I / (rho * A))
    return math.sqrt(L_sq)


@dataclass
class PlateModes:
    boundary: str
    modes: list[tuple[int, int, float]]  # (m, n, f_Hz), sorted by frequency
    flexural_rigidity: float


def plate_modes_simply_supported(
    a: float,
    b: float,
    h: float,
    E: float,
    nu: float,
    rho: float,
    m_max: int = 3,
    n_max: int = 3,
) -> PlateModes:
    """Natural frequencies of a thin Kirchhoff plate, simply supported on all
    edges, with in-plane size a × b and thickness h.

    f_mn = (π/2) · sqrt(D / (ρ h)) · ((m/a)^2 + (n/b)^2)
    D = E h^3 / (12 (1 - ν^2))
    """
    if min(a, b, h) <= 0:
        raise ValueError("a, b, h must be positive.")
    D = E * h ** 3 / (12.0 * (1.0 - nu ** 2))
    pre = (math.pi / 2.0) * math.sqrt(D / (rho * h))
    out = []
    for m in range(1, m_max + 1):
        for n in range(1, n_max + 1):
            f = pre * ((m / a) ** 2 + (n / b) ** 2)
            out.append((m, n, f))
    out.sort(key=lambda t: t[2])
    return PlateModes(boundary="simply-supported", modes=out, flexural_rigidity=D)
