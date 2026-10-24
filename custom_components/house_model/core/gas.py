# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Daily gas forecast: candidate models, rolling-origin scoring and model choice."""
import datetime as dt
from dataclasses import dataclass

from .model import Day, Model

# Last winter's shape as a loose prior: baseline ~1.5 kWh/day, slope ~3 kWh per degree-day
PRIOR = {'a': (1.5, 3.0), 'b': (3.0, 3.0)}
FIRST_HEATING_KWH = 5.0  # the card rule: fit from the first day of the window at or above this
COLD_OFF_T2 = 12.0       # a cold day with no heating at all is an away day or missing data


def make(name: str) -> Model:
    if name == 'ols15':
        return Model(window=30)
    if name == 'change_point':
        return Model(fit_base=True, window=30)
    if name == 'bayes':
        return Model(fit_base=True, window=None, half_life=21, prior=PRIOR)
    raise ValueError(name)


CANDIDATES = ('ols15', 'change_point', 'bayes')


@dataclass
class Rec:
    gas: float | None       # kWh
    t: float | None         # daily mean outdoor temperature, °C
    excluded: bool = False  # away or heating off: not fitted, not scored


def season_start(d: dt.date) -> dt.date:
    """Heating seasons start on 1 September."""
    return dt.date(d.year if d.month >= 9 else d.year - 1, 9, 1)


def build(gas: dict, temp: dict, heat_hours: dict | None, away: dict | None,
          away_minutes: int = 360) -> dict[dt.date, Rec]:
    recs = {}
    for k in sorted(set(gas) | set(temp)):
        r = Rec(gas.get(k), temp.get(k))
        prev = temp.get(k - dt.timedelta(days=1))
        if away and away.get(k, 0) >= away_minutes:
            r.excluded = True
        elif heat_hours is not None and k in heat_hours and heat_hours[k] == 0 and r.t is not None \
                and prev is not None and (r.t + prev) / 2 < COLD_OFF_T2:
            r.excluded = True
        recs[k] = r
    return recs


def t2_of(recs: dict, k: dt.date, temps: dict | None = None) -> float | None:
    """2-day mean outdoor temperature; `temps` overrides recorded ones (forecasts)."""
    def t(d):
        if temps and d in temps:
            return temps[d]
        r = recs.get(d)
        return r.t if r else None
    a, b = t(k), t(k - dt.timedelta(days=1))
    return None if a is None or b is None else (a + b) / 2


def training(recs: dict, name: str, day: dt.date) -> list[Day]:
    """Season days before `day`, aged relative to it."""
    out = []
    for k in sorted(recs):
        if not season_start(day) <= k < day:
            continue
        r, t2 = recs[k], t2_of(recs, k)
        if t2 is None:
            continue
        out.append(Day(gas=None if r.excluded else r.gas, t2=t2, age=(day - k).days))
    if name == 'ols15':
        out = [d for d in out if d.age <= 30]
        hot = [d.age for d in out if d.gas is not None and d.gas >= FIRST_HEATING_KWH]
        if hot:
            out = [d for d in out if d.age <= max(hot)]
    return out


def fitted(recs: dict, name: str, day: dt.date) -> Model | None:
    m = make(name)
    return m if m.fit(training(recs, name, day)) else None


def proxy_forecasts(recs: dict, name: str, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Rolling origin: fit on days before D, forecast D with D's observed temperature."""
    out = {}
    k = start
    while k <= end:
        r, t2 = recs.get(k), t2_of(recs, k)
        if r and t2 is not None:
            m = fitted(recs, name, k)
            if m:
                out[k] = m.predict(t2)
        k += dt.timedelta(days=1)
    return out


def errors(recs: dict, issued: dict[dt.date, float], today: dt.date, days: int) -> list[float]:
    """Actual minus forecast for scored days in the last `days` before today."""
    out = []
    for k, f in issued.items():
        r = recs.get(k)
        if r and not r.excluded and r.gas is not None and today - dt.timedelta(days=days) <= k < today:
            out.append(r.gas - f)
    return out


def mae(errs: list[float]) -> float | None:
    return sum(abs(e) for e in errs) / len(errs) if errs else None


def choose(scores: dict[str, dict], current: str | None, min_days: int = 14, margin: float = 0.05) -> str:
    """Lowest 28-day MAE wins; the current model is kept unless beaten by `margin`."""
    ok = {n: s['mae28'] for n, s in scores.items() if s['mae28'] is not None and s['days28'] >= min_days}
    if not ok:
        return current or 'bayes'
    best = min(ok, key=ok.get)
    if current in ok and ok[best] > ok[current] * (1 - margin):
        return current
    return best
