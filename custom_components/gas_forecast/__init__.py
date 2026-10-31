# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Gas forecast: forecasts the house's gas use from the weather and scores its own forecasts."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import GasForecastCoordinator

PLATFORMS = [Platform.SENSOR]

type GasForecastConfigEntry = ConfigEntry[GasForecastCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GasForecastConfigEntry) -> bool:
    coordinator = GasForecastCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: GasForecastConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GasForecastConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown_tracking()
    return unloaded
