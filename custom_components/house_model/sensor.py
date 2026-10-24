# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Sensors: today's gas forecast (with the daily forecast list) and the forecast error."""
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HouseModelConfigEntry
from .const import DOMAIN
from .coordinator import HouseModelCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: HouseModelConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([GasForecastSensor(c), GasForecastErrorSensor(c)])


class _Base(CoordinatorEntity[HouseModelCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: HouseModelCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f'{entry.entry_id}_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name='House model',
                                            entry_type=DeviceEntryType.SERVICE)


class GasForecastSensor(_Base):
    """Whole-day gas forecast for today; the daily list runs to the month end."""
    _attr_icon = 'mdi:fire'
    _unrecorded_attributes = frozenset({'forecast', 'hourly_share', 'coefficients'})

    def __init__(self, coordinator: HouseModelCoordinator) -> None:
        super().__init__(coordinator, 'gas_forecast_today')

    @property
    def native_value(self):
        return self.coordinator.data.get('today')

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        return {k: d.get(k) for k in ('model', 'coefficients', 'forecast', 'hourly_share', 'updated')}


class GasForecastErrorSensor(_Base):
    """Mean absolute error of the active model over the last 28 scored days."""
    _attr_icon = 'mdi:target-variant'
    _unrecorded_attributes = frozenset({'models'})

    def __init__(self, coordinator: HouseModelCoordinator) -> None:
        super().__init__(coordinator, 'gas_forecast_error')

    @property
    def native_value(self):
        d = self.coordinator.data
        return (d.get('scores', {}).get(d.get('model')) or {}).get('mae28')

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        return {'model': d.get('model'), 'models': d.get('scores')}
