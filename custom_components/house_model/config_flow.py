# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Paul Owen
"""Config flow: pick the gas meter, outdoor temperature and weather entities."""
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (CONF_CLIMATE, CONF_GAS, CONF_HEATING_TIME, CONF_OUTDOOR,
                    CONF_OUTDOOR_FALLBACK, CONF_WEATHER, DOMAIN)

SCHEMA = vol.Schema({
    vol.Required(CONF_GAS): selector.EntitySelector(selector.EntitySelectorConfig(domain='sensor', device_class='energy')),
    vol.Required(CONF_OUTDOOR): selector.EntitySelector(selector.EntitySelectorConfig(domain='sensor', device_class='temperature')),
    vol.Optional(CONF_OUTDOOR_FALLBACK): selector.EntitySelector(selector.EntitySelectorConfig(domain='sensor', device_class='temperature')),
    vol.Optional(CONF_HEATING_TIME): selector.EntitySelector(selector.EntitySelectorConfig(domain='sensor')),
    vol.Optional(CONF_CLIMATE): selector.EntitySelector(selector.EntitySelectorConfig(domain='climate')),
    vol.Required(CONF_WEATHER): selector.EntitySelector(selector.EntitySelectorConfig(domain='weather')),
})


class HouseModelConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title='House model', data=user_input)
        return self.async_show_form(step_id='user', data_schema=SCHEMA)
