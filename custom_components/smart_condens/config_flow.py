"""Setup: the user picks their own entities, nothing is hard coded."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import const as c

try:  # Home Assistant 2026.12+ replaced voluptuous with probatio.
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol

TOPIC_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$")


def _entity(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains)))


def _number(minimum: float, maximum: float, step: float | str, unit: str | None = None):
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def main_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(c.CONF_OUTDOOR): _entity("sensor"),
            vol.Required(c.CONF_FLOW): _entity("sensor"),
            vol.Required(c.CONF_RETURN): _entity("sensor"),
            vol.Optional(c.CONF_BURNER_HEATING): _entity("binary_sensor"),
            vol.Optional(c.CONF_BURNER_DHW): _entity("binary_sensor"),
            vol.Optional(c.CONF_STARTS): _entity("sensor"),
            vol.Optional(c.CONF_GAS): _entity("sensor"),
            vol.Optional(c.CONF_PRICE, default=0): _number(0, 1, "any", "€/kWh"),
            vol.Optional(c.CONF_CHANGE_DATE): selector.DateSelector(),
            vol.Optional(c.CONF_GD_BASE, default=c.DEFAULT_GD_BASE): _number(
                10, 22, 0.5, "°C"
            ),
            vol.Optional(c.CONF_DHW_BASE, default=0): _number(0, 100, 0.1, "kWh"),
            vol.Optional(c.CONF_W_ELEMENT, default=c.DEFAULT_W_ELEMENT): _number(
                30, 300, 1, "W"
            ),
            vol.Optional(c.CONF_DASHBOARD, default=True): selector.BooleanSelector(),
            vol.Optional(c.CONF_ALLOW_WRITE, default=False): selector.BooleanSelector(),
            vol.Optional(c.CONF_MQTT_TOPIC, default="ebusd"): selector.TextSelector(),
            vol.Optional(c.CONF_CIRCUIT, default="bai"): selector.TextSelector(),
        }
    )


def _errors(user_input: dict[str, Any]) -> dict[str, str]:
    errors = {}
    for key in (c.CONF_MQTT_TOPIC, c.CONF_CIRCUIT):
        if not TOPIC_RE.match(user_input.get(key) or ""):
            errors[key] = "invalid_topic"
    return errors


class SmartCondensConfigFlow(ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _errors(user_input)):
            return self.async_create_entry(title="Smart Condens", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(main_schema(), user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartCondensOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {c.SUBENTRY_ROOM: RoomSubentryFlow}


class SmartCondensOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _errors(user_input)):
            return self.async_create_entry(data=user_input)
        current = user_input or dict(
            self.config_entry.options or self.config_entry.data
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(main_schema(), current),
            errors=errors,
        )


ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(c.CONF_NAME): selector.TextSelector(),
        vol.Required(c.CONF_CLIMATE): _entity("climate"),
        vol.Optional(c.CONF_TEMP): _entity("sensor"),
        vol.Optional(c.CONF_DEMAND): _entity("sensor", "binary_sensor"),
        vol.Optional(c.CONF_ELEMENTS, default=0): _number(0, 60, 1),
        vol.Optional(c.CONF_ORDER, default=0): _number(0, 60, 1),
    }
)


def clean_name(name: str) -> str:
    """Room names end up inside Markdown templates: keep them harmless."""
    return re.sub(r"[{}|%`<>\[\]\"'\\\n\r]", "", name).strip()[:40]


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or edit one room."""

    def _name_error(self, name: str, skip: str | None) -> dict[str, str]:
        if not name:
            return {c.CONF_NAME: "empty_name"}
        for sid, sub in self._get_entry().subentries.items():
            if sid != skip and sub.title.casefold() == name.casefold():
                return {c.CONF_NAME: "duplicate_name"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = clean_name(user_input[c.CONF_NAME])
            if not (errors := self._name_error(name, None)):
                return self.async_create_entry(
                    title=name, data={**user_input, c.CONF_NAME: name}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(ROOM_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = clean_name(user_input[c.CONF_NAME])
            if not (errors := self._name_error(name, sub.subentry_id)):
                return self.async_update_and_abort(
                    self._get_entry(),
                    sub,
                    title=name,
                    data={**user_input, c.CONF_NAME: name},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                ROOM_SCHEMA, user_input or dict(sub.data)
            ),
            errors=errors,
        )
