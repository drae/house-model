# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""End-to-end: config flow, setup on synthetic statistics, sensors and away tracking."""
import datetime as dt
import math
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.house_model.const import DOMAIN

CONF = {
    'gas_energy': 'sensor.gas',
    'outdoor_temperature': 'sensor.outdoor',
    'heating_time': 'sensor.heating_time',
    'climate': 'climate.thermostat',
    'weather': 'weather.home',
}
A, B, BASE = 1.0, 3.0, 15.0


def temp_of(day: dt.date) -> float:
    return 10 + 4 * math.sin(day.toordinal() / 5)


def synthetic(hass, start, end, ids, period, units, types):
    """Hourly rows from `start` to now: gas booked at 07:00, temperature constant per day."""
    tz = dt_util.get_default_time_zone()
    out = {i: [] for i in ids}
    t = start.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)
    now = dt_util.utcnow()
    total, heat = 0.0, 0.0
    while t < now:
        local = t.astimezone(tz)
        d = local.date()
        t2 = (temp_of(d) + temp_of(d - dt.timedelta(days=1))) / 2
        if local.hour == 7:
            total += A + B * max(0.0, BASE - t2)
        heat = 0.0 if local.hour == 1 else heat + (0.1 if local.hour == 7 else 0.0)
        ts = t.timestamp()
        out['sensor.gas'].append({'start': ts, 'sum': total})
        out['sensor.outdoor'].append({'start': ts, 'mean': temp_of(d)})
        out['sensor.heating_time'].append({'start': ts, 'max': heat})
        t += dt.timedelta(hours=1)
    return out


@pytest.fixture(autouse=True)
def auto_enable(recorder_mock, enable_custom_integrations):
    yield


async def _weather(hass: HomeAssistant):
    async def handler(call):
        today = dt_util.now().date()
        return {'weather.home': {'forecast': [
            {'datetime': dt_util.start_of_local_day(today + dt.timedelta(days=i)).isoformat(),
             'temperature': temp_of(today + dt.timedelta(days=i)) + 3, 'templow': temp_of(today + dt.timedelta(days=i)) - 3}
            for i in range(10)]}}
    hass.services.async_register('weather', 'get_forecasts', handler, supports_response=SupportsResponse.ONLY)


async def test_config_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': SOURCE_USER})
    assert result['type'] is FlowResultType.FORM
    with patch('custom_components.house_model.async_setup_entry', return_value=True), \
            patch('custom_components.house_model.async_unload_entry', return_value=True):
        result = await hass.config_entries.flow.async_configure(result['flow_id'], CONF)
        await hass.async_block_till_done()
        assert result['type'] is FlowResultType.CREATE_ENTRY
        assert result['data'] == CONF
        await hass.config_entries.async_remove(result['result'].entry_id)


async def test_setup_forecasts_and_scores(hass: HomeAssistant):
    await hass.config.async_update(time_zone='Europe/London')
    await _weather(hass)
    hass.states.async_set('climate.thermostat', 'heat')
    entry = MockConfigEntry(domain=DOMAIN, data=CONF)
    entry.add_to_hass(hass)
    with patch('custom_components.house_model.coordinator.statistics_during_period', side_effect=synthetic):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    today = dt_util.now().date()
    t2 = (temp_of(today) + temp_of(today - dt.timedelta(days=1))) / 2
    st = hass.states.get('sensor.house_model_gas_forecast_today')
    assert st is not None, [s.entity_id for s in hass.states.async_all()]
    # the forecast uses (hi + lo) / 2 = the true mean, so every model should land on the line
    assert float(st.state) == pytest.approx(A + B * max(0.0, BASE - t2), abs=0.3)
    assert len(st.attributes['forecast']) >= 10
    assert st.attributes['hourly_share'][7] == pytest.approx(1.0)
    assert st.attributes['model'] in ('ols15', 'change_point', 'bayes')

    err = hass.states.get('sensor.house_model_gas_forecast_error')
    assert float(err.state) < 0.5
    assert set(err.attributes['models']) == {'ols15', 'change_point', 'bayes', 'bayes_heating'}

    # Away tracking: off then back on accumulates minutes for today
    coordinator = entry.runtime_data
    hass.states.async_set('climate.thermostat', 'off')
    await hass.async_block_till_done()
    coordinator._off_since -= dt.timedelta(minutes=30)
    hass.states.async_set('climate.thermostat', 'heat')
    await hass.async_block_till_done()
    # summed: just after midnight the 30 minutes are split across two days
    assert sum(coordinator.saved['away'].values()) == pytest.approx(30, abs=1)

    assert await hass.config_entries.async_unload(entry.entry_id)


def _shifted_evening():
    """The real 24 Oct evening moved to end an hour before now, in whole half-hours."""
    from fixtures_evenings import BATHROOM_24, CLIMATE_24, GAS_24, KITCHEN_24, POWER_24, ts
    off = (dt_util.utcnow().timestamp() - 3600 - ts('2026-10-25T00:30')) // 1800 * 1800
    sh = lambda rows: [(t + off, *rest) for t, *rest in rows]
    return {'start': ts('2026-10-24T16:30') + off, 'gas': sh(GAS_24), 'shower': [sh(BATHROOM_24)],
            'hob': [sh(KITCHEN_24)], 'climate': sh(CLIMATE_24), 'power': sh(POWER_24)}


async def test_gas_split_on_a_real_evening(hass: HomeAssistant):
    await hass.config.async_update(time_zone='Europe/London')
    await _weather(hass)
    hass.states.async_set('climate.thermostat', 'auto')
    conf = {**CONF, 'shower_humidity': ['sensor.bathroom_humidity'], 'hob_humidity': ['sensor.kitchen_humidity'],
            'electricity_power': 'sensor.power'}
    entry = MockConfigEntry(domain=DOMAIN, data=conf)
    entry.add_to_hass(hass)
    with patch('custom_components.house_model.coordinator.statistics_during_period', side_effect=synthetic), \
            patch('custom_components.house_model.coordinator.HouseModelCoordinator._history',
                  side_effect=lambda start: _shifted_evening()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    for use in ('heating', 'hot_water', 'hob'):
        st = hass.states.get(f'sensor.house_model_gas_{use}_today')
        assert st is not None and st.attributes['device_class'] == 'energy'
    days = entry.runtime_data.saved['split'].values()
    assert sum(d['hot_water'] for d in days) == pytest.approx(4.019, abs=1e-3)
    assert sum(d['heating'] for d in days) == pytest.approx(5.492 + 5.136, abs=1e-3)
    assert sum(d['hob'] for d in days) == 0
    assert sum(d['boost_heating'] for d in days) == pytest.approx(5.136, abs=1e-3)
    kw = hass.states.get('sensor.house_model_gas_heating_today').attributes['kw']
    assert 14 < kw['dhw'] < 15 and 17 < kw['heat'] < 18
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_adds_split_sensors(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=CONF)
    entry.add_to_hass(hass)
    with patch('custom_components.house_model.async_setup_entry', return_value=True), \
            patch('custom_components.house_model.async_unload_entry', return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result['type'] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result['flow_id'], {**CONF, 'shower_humidity': ['sensor.bathroom_humidity']})
        assert result['type'] is FlowResultType.CREATE_ENTRY
        assert entry.options['shower_humidity'] == ['sensor.bathroom_humidity']
        await hass.config_entries.async_remove(entry.entry_id)
