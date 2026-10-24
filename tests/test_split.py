# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
import datetime as dt

import pytest

from core import split
from fixtures_evenings import (BATHROOM_24, CLIMATE_24, GAS_22, GAS_24, KITCHEN_22, KITCHEN_24, POWER_22,
                               POWER_24, TZ, ts)

KW = {'heat': 17.0, 'dhw': 14.0, 'hob': 1.3}


def test_shower_detected_from_bathroom_humidity():
    evs = split.detect(BATHROOM_24, 'shower', **split.SHOWER)
    assert len(evs) == 1
    e = evs[0]
    assert e.start == ts('2026-10-24T23:15:05') and e.end == ts('2026-10-24T23:31:28')
    assert e.rise == 42


def test_hob_detected_through_a_kettle():
    evs = split.events([], [KITCHEN_22], POWER_22)
    assert [(e.kind, e.start, e.end) for e in evs] == [('hob', ts('2026-10-22T20:04:52'), ts('2026-10-22T20:24:19'))]


def test_kettle_steam_and_shower_drift_are_not_hob():
    evs = split.events([BATHROOM_24], [KITCHEN_24], POWER_24)
    assert [e.kind for e in evs] == ['shower']


def test_oven_is_not_hob():
    oven = [(t, 2.5) for t, _ in POWER_22]
    assert split.events([], [KITCHEN_22], oven) == []


def test_evening_24_split():
    evs = split.events([BATHROOM_24], [KITCHEN_24], POWER_24)
    slots = split.build_slots(ts('2026-10-24T16:30'), ts('2026-10-25T00:30'), GAS_24, CLIMATE_24, evs, KW)
    s17, s19 = slots[ts('2026-10-24T17:00')], slots[ts('2026-10-24T19:00')]
    assert s17.gas == pytest.approx(5.492) and s19.gas == pytest.approx(5.136)
    assert s19.boost_heat == s19.heat == pytest.approx(ts('2026-10-24T19:21:32') - ts('2026-10-24T19:03:27'))
    # 19:30-23:30 has no reading until 23:30; it all belongs to the shower slot
    assert slots[ts('2026-10-24T23:00')].gas == pytest.approx(3.907)
    assert slots[ts('2026-10-24T23:30')].gas == pytest.approx(0.112)
    assert not any(s.lumped for s in slots.values())
    days = split.daily(slots, KW, TZ)
    d24 = days[dt.date(2026, 10, 24)]
    assert d24['heating'] == pytest.approx(5.492 + 5.136)
    assert d24['boost_heating'] == pytest.approx(5.136)
    assert d24['hot_water'] == pytest.approx(4.019)
    assert d24['hob'] == 0


def test_learned_rates_from_the_two_evenings():
    evs = split.events([BATHROOM_24], [KITCHEN_24], POWER_24)
    s24 = split.build_slots(ts('2026-10-24T16:30'), ts('2026-10-25T00:30'), GAS_24, CLIMATE_24, evs, KW)
    ev22 = split.events([], [KITCHEN_22], POWER_22)
    s22 = split.build_slots(ts('2026-10-22T19:00'), ts('2026-10-22T21:00'), GAS_22, [(ts('2026-10-22T19:00'), 'idle', 'none')], ev22, KW)
    kw = split.learn_kw({**s22, **s24}, ev22 + evs, TZ)
    # clean evidence: heat 10.63 kWh / 0.6 h, shower 4.02 kWh / 0.27 h, hob 0.446 kWh / 0.32 h
    assert 17 < kw['heat'] < 18
    assert 14 < kw['dhw'] < 15
    assert 1.3 < kw['hob'] < 1.4


def test_late_lump_is_flagged():
    t = ts('2026-10-20T00:00')
    gas = [(t, 0.0), (t + 10 * 3600 + 20, 8.0)]  # a day's gas booked at once, nothing seen
    slots = split.build_slots(t, t + 12 * 3600, gas, [(t, 'idle', 'none')], [], KW)
    assert all(s.lumped for k, s in slots.items() if k < t + 10 * 3600)


def test_heating_during_shower_counts_as_hot_water():
    t = ts('2026-10-26T07:00')
    clim = [(t, 'heating', 'none'), (t + 1800, 'idle', 'none')]
    ev = [split.Event('shower', t + 600, t + 1200, 30)]
    slots = split.build_slots(t, t + 1800, [(t, 0.0), (t + 1830, 7.0)], clim, ev, KW)
    s = slots[t]
    assert s.heat == 1200 and s.shower == 600
    parts = split.split_slot(s, KW)
    assert parts['hot_water'] == pytest.approx(7.0 * 14 * 600 / (14 * 600 + 17 * 1200))


def test_brief_bathroom_draw_shares_a_slot_with_the_hob():
    t = ts('2026-10-19T14:30')
    bath = [(t, 54.0), (t + 60, 56.0), (t + 100, 58.0), (t + 140, 60.0), (t + 400, 59.0), (t + 500, 56.0)]
    evs = split.events([bath], [], None)
    assert [(e.kind, e.end - e.start) for e in evs] == [('shower', 80.0)]
    hob = split.Event('hob', t + 300, t + 1500, 7)
    slots = split.build_slots(t, t + 1800, [(t, 0.0), (t + 1820, 1.0)], [(t, 'idle', 'none')], evs + [hob], KW)
    parts = split.split_slot(slots[t], KW)
    assert parts['hot_water'] > 0.4 and parts['hob'] < 0.6
    # too short to learn a rate from; and a 4 kW "hob" is not learned either
    assert split.evidence(slots, evs + [hob], TZ) == {}
