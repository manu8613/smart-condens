"""Setup wizard: proposes the user's own entities and rooms for them to review."""

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
from . import detect

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
            vol.Optional(c.CONF_GAS_TUR, default=True): selector.BooleanSelector(),
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
    """House entities, then which valves to analyse, then one form per room."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._guesses: list[detect.RoomGuess] = []
        self._pending: list[detect.RoomGuess] = []
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _errors(user_input)):
            self._data = user_input
            self._guesses = detect.room_guesses(self.hass, user_input)
            if self._guesses:
                return await self.async_step_rooms()
            return self._create()
        suggested = user_input or detect.house_suggestions(self.hass)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(main_schema(), suggested),
            errors=errors,
        )

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            chosen = user_input.get(c.CONF_ROOMS) or []
            self._pending = [g for g in self._guesses if g.climate in chosen]
            self._rooms = []
            return await self._next_room()
        schema = vol.Schema(
            {
                vol.Optional(c.CONF_ROOMS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate"], multiple=True)
                )
            }
        )
        selected = [g.climate for g in self._guesses if g.preselected]
        return self.async_show_form(
            step_id="rooms",
            data_schema=self.add_suggested_values_to_schema(
                schema, {c.CONF_ROOMS: selected}
            ),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        guess = self._pending[0]
        errors: dict[str, str] = {}
        if user_input is not None:
            name = clean_name(user_input[c.CONF_NAME])
            taken = [room["title"] for room in self._rooms]
            if not (errors := _name_error(name, taken)):
                data = {**user_input, c.CONF_NAME: name, c.CONF_CLIMATE: guess.climate}
                self._rooms.append(
                    {
                        "subentry_type": c.SUBENTRY_ROOM,
                        "title": name,
                        "data": data,
                        "unique_id": None,
                    }
                )
                self._pending.pop(0)
                return await self._next_room()
        return self._room_form(user_input or guess.data, errors)

    async def _next_room(self) -> ConfigFlowResult:
        if not self._pending:
            return self._create()
        return self._room_form(self._pending[0].data, {})

    def _room_form(
        self, values: dict[str, Any], errors: dict[str, str]
    ) -> ConfigFlowResult:
        climate = self._pending[0].climate
        state = self.hass.states.get(climate)
        done = len(self._rooms)
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(WIZARD_ROOM_SCHEMA, values),
            errors=errors,
            description_placeholders={
                "current": str(done + 1),
                "total": str(done + len(self._pending)),
                "valve": f"{state.name if state else climate} ({climate})",
            },
        )

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title="Smart Condens", data=self._data, subentries=self._rooms
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


ROOM_FIELDS = {
    vol.Required(c.CONF_NAME): selector.TextSelector(),
    vol.Required(c.CONF_CLIMATE): _entity("climate"),
    vol.Optional(c.CONF_TEMP): _entity("sensor"),
    vol.Optional(c.CONF_DEMAND): _entity("sensor", "binary_sensor"),
    vol.Optional(c.CONF_ELEMENTS, default=0): _number(0, 60, 1),
    vol.Optional(c.CONF_ORDER, default=0): _number(0, 60, 1),
}
ROOM_SCHEMA = vol.Schema(ROOM_FIELDS)
# In the wizard the valve of each form is already chosen.
WIZARD_ROOM_SCHEMA = vol.Schema(
    {key: value for key, value in ROOM_FIELDS.items() if key != c.CONF_CLIMATE}
)


def clean_name(name: str) -> str:
    """Room names end up inside Markdown templates: keep them harmless."""
    return re.sub(r"[{}|%`<>\[\]\"'\\\n\r]", "", name).strip()[:40]


def _name_error(name: str, taken: list[str]) -> dict[str, str]:
    if not name:
        return {c.CONF_NAME: "empty_name"}
    if name.casefold() in {other.casefold() for other in taken}:
        return {c.CONF_NAME: "duplicate_name"}
    return {}


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or edit one room."""

    def _name_error(self, name: str, skip: str | None) -> dict[str, str]:
        rooms = self._get_entry().subentries.items()
        return _name_error(name, [sub.title for sid, sub in rooms if sid != skip])

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
