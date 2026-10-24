# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Hourly refresh: read statistics and the weather forecast, refit, score and forecast."""
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (CONF_CLIMATE, CONF_GAS, CONF_HEATING_TIME, CONF_OUTDOOR,
                    CONF_OUTDOOR_FALLBACK, CONF_WEATHER, DOMAIN, KEEP_AWAY_DAYS,
                    KEEP_ISSUED_DAYS, STORE_VERSION)
from .core import data, gas

_LOGGER = logging.getLogger(__name__)
FORECAST_DAYS = 10


class HouseModelCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=dt.timedelta(hours=1), config_entry=entry)
        self.conf = entry.data
        self._store = Store(hass, STORE_VERSION, f'{DOMAIN}.{entry.entry_id}')
        # issued: model -> ISO date -> kWh forecast made on that day; away: ISO date -> minutes with heating off
        self.saved = {'issued': {}, 'away': {}, 'active': None}
        self._proxy: dict[str, dict[dt.date, float]] = {}
        self._proxy_day: dt.date | None = None
        self._off_since: dt.datetime | None = None
        self._unsub = None
        self._last_fc: dict[dt.date, float] = {}

    async def async_load(self) -> None:
        if stored := await self._store.async_load():
            self.saved.update(stored)
        if climate := self.conf.get(CONF_CLIMATE):
            st = self.hass.states.get(climate)
            if st and st.state == 'off':
                self._off_since = dt_util.now()
            self._unsub = async_track_state_change_event(self.hass, climate, self._climate_changed)

    async def async_shutdown_tracking(self) -> None:
        self._flush_off(dt_util.now())
        if self._unsub:
            self._unsub()
        await self._store.async_save(self.saved)

    @callback
    def _climate_changed(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.now()
        old, new = event.data['old_state'], event.data['new_state']
        if old and old.state == 'off':
            self._flush_off(now)
        self._off_since = now if new and new.state == 'off' else None

    def _flush_off(self, now: dt.datetime) -> None:
        """Add minutes with the heating off to each local day they fall in."""
        t = self._off_since
        if t is None:
            return
        while t < now:
            nxt = min(now, dt_util.start_of_local_day(t.date() + dt.timedelta(days=1)))
            k = t.date().isoformat()
            self.saved['away'][k] = self.saved['away'].get(k, 0) + (nxt - t).total_seconds() / 60
            t = nxt
        self._off_since = now

    async def _forecast_temps(self, tz: ZoneInfo) -> dict[dt.date, float]:
        entity = self.conf[CONF_WEATHER]
        try:
            resp = await self.hass.services.async_call(
                'weather', 'get_forecasts', {'entity_id': entity, 'type': 'daily'}, blocking=True, return_response=True)
        except Exception as err:  # weather integration down: keep the last forecast
            _LOGGER.warning('weather forecast unavailable: %s', err)
            return self._last_fc
        out = {}
        for f in resp.get(entity, {}).get('forecast', []):
            if f.get('temperature') is None:
                continue
            k = dt_util.parse_datetime(f['datetime']).astimezone(tz).date()
            lo = f.get('templow')
            out[k] = (f['temperature'] + lo) / 2 if lo is not None else f['temperature']
        self._last_fc = out
        return out

    async def _async_update_data(self) -> dict:
        tz = ZoneInfo(self.hass.config.time_zone)
        now = dt_util.now()
        today = now.date()
        self._flush_off(now)
        start = dt_util.start_of_local_day(gas.season_start(today) - dt.timedelta(days=2))
        ids = {self.conf[CONF_GAS], self.conf[CONF_OUTDOOR]}
        for key in (CONF_OUTDOOR_FALLBACK, CONF_HEATING_TIME):
            if self.conf.get(key):
                ids.add(self.conf[key])
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, start, None, ids, 'hour', None, {'sum', 'mean', 'max'})
        fc = await self._forecast_temps(tz)
        self._prune(today)
        away = {dt.date.fromisoformat(k): v for k, v in self.saved['away'].items()}
        result = await self.hass.async_add_executor_job(self._compute, stats, fc, away, tz, today, now)
        await self._store.async_save(self.saved)
        return result

    def _compute(self, stats: dict, fc: dict, away: dict, tz: ZoneInfo, today: dt.date, now: dt.datetime) -> dict:
        rows = lambda key: stats.get(self.conf.get(key), []) if self.conf.get(key) else []
        gas_rows = rows(CONF_GAS)
        temp = data.daily_mean(rows(CONF_OUTDOOR), tz)
        for k, v in data.daily_mean(rows(CONF_OUTDOOR_FALLBACK), tz).items():
            temp.setdefault(k, v)
        heat = data.daily_running_max(rows(CONF_HEATING_TIME), tz) if self.conf.get(CONF_HEATING_TIME) else None
        recs = gas.build(data.daily_from_sum(gas_rows, tz), temp, heat, away)

        # Rolling-origin scores on observed weather until the model's own issued forecasts take over
        if self._proxy_day != today:
            first = gas.season_start(today)
            self._proxy = {n: gas.proxy_forecasts(recs, n, first, today - dt.timedelta(days=1)) for n in gas.CANDIDATES}
            self._proxy_day = today

        # Forecast temperatures: the weather forecast, then the last week's mean beyond it
        recent = [temp[k] for k in temp if today - dt.timedelta(days=7) <= k < today]
        fallback = sum(recent) / len(recent) if recent else None
        month_end = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        horizon = max(today + dt.timedelta(days=FORECAST_DAYS - 1), month_end)
        temps, k = {}, today
        while k <= horizon:
            if k in fc or fallback is not None:
                temps[k] = fc.get(k, fallback)
            k += dt.timedelta(days=1)

        scores, models = {}, {}
        for n in gas.CANDIDATES:
            m = gas.fitted(recs, n, today)
            models[n] = m
            issued = self.saved['issued'].setdefault(n, {})
            t2 = gas.t2_of(recs, today, temps)
            if m and t2 is not None and today.isoformat() not in issued:
                issued[today.isoformat()] = round(m.predict(t2), 3)
            merged = dict(self._proxy.get(n, {}))
            merged.update({dt.date.fromisoformat(d): v for d, v in issued.items()})
            e14, e28 = gas.errors(recs, merged, today, 14), gas.errors(recs, merged, today, 28)
            scores[n] = {'mae14': gas.mae(e14), 'mae28': gas.mae(e28), 'days14': len(e14), 'days28': len(e28)}
        active = gas.choose(scores, self.saved['active'])
        if active != self.saved['active']:
            _LOGGER.info('gas model: %s -> %s', self.saved['active'], active)
            self.saved['active'] = active

        m = models.get(active)
        forecast = []
        for k in sorted(temps):
            t2 = gas.t2_of(recs, k, temps)
            if m and t2 is not None:
                forecast.append({'date': k.isoformat(), 'kwh': round(m.predict(t2), 2),
                                 'weather': 'forecast' if k in fc else 'recent'})
        return {
            'today': forecast[0]['kwh'] if forecast and forecast[0]['date'] == today.isoformat() else None,
            'forecast': forecast,
            'hourly_share': data.hourly_share(gas_rows, tz, today),
            'model': active,
            'coefficients': {'a': round(m.a, 3), 'b': round(m.b, 3), 'base': m.base, 'days': m.days} if m else None,
            'scores': {n: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()} for n, s in scores.items()},
            'updated': now.isoformat(),
        }

    def _prune(self, today: dt.date) -> None:
        old = (today - dt.timedelta(days=KEEP_ISSUED_DAYS)).isoformat()
        for issued in self.saved['issued'].values():
            for d in [d for d in issued if d < old]:
                del issued[d]
        old = (today - dt.timedelta(days=KEEP_AWAY_DAYS)).isoformat()
        for d in [d for d in self.saved['away'] if d < old]:
            del self.saved['away'][d]
