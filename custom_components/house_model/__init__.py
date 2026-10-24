# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""House model: forecasts the house's gas use from the weather and scores its own forecasts."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import HouseModelCoordinator

PLATFORMS = [Platform.SENSOR]

type HouseModelConfigEntry = ConfigEntry[HouseModelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HouseModelConfigEntry) -> bool:
    coordinator = HouseModelCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HouseModelConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown_tracking()
    return unloaded
