# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np

from core import data, gas
from core.model import Day, Model

TZ = ZoneInfo('Europe/London')


def hours(start: dt.datetime, n: int):
    """UTC hour starts from a local start time."""
    t0 = start.astimezone(dt.timezone.utc)
    return [(t0 + dt.timedelta(hours=i)).timestamp() for i in range(n)]


def test_daily_from_sum_across_clock_change():
    # 25 Oct 2026 has 25 local hours; 1 kWh booked every hour
    ts = hours(dt.datetime(2026, 10, 24, 23, tzinfo=TZ), 27)
    rows = [{'start': t, 'sum': float(i)} for i, t in enumerate(ts)]
    out = data.daily_from_sum(rows, TZ)
    assert out[dt.date(2026, 10, 25)] == 25.0


def test_daily_from_sum_drops_resets():
    ts = hours(dt.datetime(2026, 10, 1, 0, tzinfo=TZ), 4)
    rows = [{'start': ts[0], 'sum': 10}, {'start': ts[1], 'sum': 11}, {'start': ts[2], 'sum': 0}, {'start': ts[3], 'sum': 2}]
    assert data.daily_from_sum(rows, TZ) == {dt.date(2026, 10, 1): 3.0}


def test_running_max_skips_midnight_carry_over():
    ts = hours(dt.datetime(2026, 10, 12, 0, tzinfo=TZ), 24)
    rows = [{'start': ts[0], 'max': 0.39}] + [{'start': t, 'max': 0.29 if i > 7 else 0.0} for i, t in enumerate(ts[1:], 1)]
    assert data.daily_running_max(rows, TZ) == {dt.date(2026, 10, 12): 0.29}


def test_hourly_share_sums_to_one():
    ts = hours(dt.datetime(2026, 10, 10, 0, tzinfo=TZ), 24 * 3)
    s, rows = 0.0, []
    for t in ts:
        h = dt.datetime.fromtimestamp(t, TZ).hour
        s += 3.0 if h == 7 else 1.0 if h == 18 else 0.0
        rows.append({'start': t, 'sum': s})
    share = data.hourly_share(rows, TZ, dt.date(2026, 10, 13))
    assert abs(sum(share) - 1) < 1e-9
    assert share[7] == 0.75 and share[18] == 0.25


def test_model_recovers_line_and_base():
    rng = np.random.default_rng(0)
    t2 = rng.uniform(2, 18, 60)
    days = [Day(gas=1.0 + 3.0 * max(0, 14.5 - t), t2=float(t)) for t in t2]
    m = Model(fit_base=True, window=None)
    assert m.fit(days)
    assert m.base == 14.5 and abs(m.a - 1) < 1e-6 and abs(m.b - 3) < 1e-6


def test_prior_holds_early_season():
    # Two warm days alone can't pin a slope: the prior keeps it near 3
    days = [Day(gas=1.0, t2=16.0, age=1), Day(gas=1.2, t2=15.5, age=2)]
    m = Model(window=None, prior=gas.PRIOR, min_days=1)
    assert m.fit(days)
    assert 2.0 < m.b < 4.0


def test_cold_day_without_heating_is_excluded():
    k = dt.date(2026, 10, 8)
    recs = gas.build({k: 0.4}, {k: 10.0, k - dt.timedelta(days=1): 11.0}, {k: 0.0}, None)
    assert recs[k].excluded


def test_ols15_window_starts_at_first_heating_day():
    day = dt.date(2026, 10, 24)
    temps, gases = {}, {}
    for i in range(1, 32):
        k = day - dt.timedelta(days=i)
        temps[k] = 10.0
        gases[k] = 8.0 if i <= 14 else 0.5
    recs = gas.build(gases, temps, None, None)
    tr = gas.training(recs, 'ols15', day)
    assert max(d.age for d in tr) == 14


def test_choose_keeps_current_unless_clearly_beaten():
    s = lambda m: {'mae28': m, 'days28': 20}
    assert gas.choose({'ols15': s(2.0), 'bayes': s(1.95)}, 'ols15') == 'ols15'
    assert gas.choose({'ols15': s(2.0), 'bayes': s(1.8)}, 'ols15') == 'bayes'
    assert gas.choose({'ols15': {'mae28': 1.0, 'days28': 3}}, None) == 'bayes'
