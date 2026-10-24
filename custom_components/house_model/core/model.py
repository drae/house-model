# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Degree-day regressions of daily gas use on the 2-day mean outdoor temperature."""
from dataclasses import dataclass, field

import numpy as np

# Residual scale (kWh/day) that turns prior standard deviations into ridge weights
NOISE = 3.0


@dataclass
class Day:
    gas: float | None  # kWh, None when unknown or excluded
    t2: float          # mean of the day's and the previous day's outdoor temperature, °C
    age: int = 0       # days before the forecast day


def _wls(X, y, w, prior_mean=None, prior_sd=None):
    """Weighted least squares; a Gaussian prior per coefficient adds ridge rows."""
    sw = np.sqrt(w)
    A, b = X * sw[:, None], y * sw
    if prior_mean is not None:
        P = np.diag(NOISE / np.asarray(prior_sd, dtype=float))
        A = np.vstack([A, P])
        b = np.concatenate([b, P @ np.asarray(prior_mean, dtype=float)])
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    return coef


@dataclass
class Model:
    """gas = a + b * max(0, base - t2), plus a fixed offset (the non-heating gas, for heating-only fits)."""

    base: float = 15.0
    fit_base: bool = False          # change-point: choose the base by least squares
    window: int | None = 30         # fit on days up to this age; None = every day given
    half_life: float | None = None  # exponential forgetting, days
    prior: dict = field(default_factory=dict)  # coefficient -> (mean, sd)
    min_days: int = 7
    a: float = 0.0
    b: float = 0.0
    days: int = 0
    offset: float = 0.0

    def fit(self, days: list[Day]) -> bool:
        days = [d for d in days if d.gas is not None and (self.window is None or d.age <= self.window)]
        if len(days) < self.min_days:
            return False
        y = np.array([d.gas for d in days], dtype=float)
        t2 = np.array([d.t2 for d in days], dtype=float)
        ages = np.array([d.age for d in days], dtype=float)
        w = 0.5 ** (ages / self.half_life) if self.half_life else np.ones(len(days))
        pm = ps = None
        if self.prior:
            pm = [self.prior.get(n, (0.0, 1e6))[0] for n in ('a', 'b')]
            ps = [self.prior.get(n, (0.0, 1e6))[1] for n in ('a', 'b')]
        best = None
        for base in (np.arange(10.0, 18.01, 0.5) if self.fit_base else [self.base]):
            X = np.column_stack([np.ones(len(days)), np.maximum(0.0, base - t2)])
            c = _wls(X, y, w, pm, ps)
            sse = float(np.sum(w * (y - X @ c) ** 2))
            if best is None or sse < best[0]:
                best = (sse, float(base), c)
        _, self.base, c = best
        self.a, self.b, self.days = float(c[0]), float(c[1]), len(days)
        return True

    def predict(self, t2: float) -> float:
        return max(0.0, self.a + self.b * max(0.0, self.base - t2)) + self.offset
