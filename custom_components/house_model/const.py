# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Constants for House model."""
DOMAIN = 'house_model'

CONF_GAS = 'gas_energy'
CONF_OUTDOOR = 'outdoor_temperature'
CONF_OUTDOOR_FALLBACK = 'outdoor_temperature_fallback'
CONF_HEATING_TIME = 'heating_time'
CONF_CLIMATE = 'climate'
CONF_WEATHER = 'weather'
CONF_SHOWER_HUMIDITY = 'shower_humidity'
CONF_HOB_HUMIDITY = 'hob_humidity'
CONF_POWER = 'electricity_power'

STORE_VERSION = 1
KEEP_ISSUED_DAYS = 120
KEEP_AWAY_DAYS = 400
KEEP_SPLIT_DAYS = 400
SPLIT_ATTR_DAYS = 35  # days of split on gas_heating_today's days attribute
HISTORY_DAYS = 10     # the recorder's default state history; the split backfills this far once
EVIDENCE_DAYS = 30    # days of clean events pooled into the learned kW rates
