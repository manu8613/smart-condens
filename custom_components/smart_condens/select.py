"""Proposed pump setting: not sent until prepared and confirmed."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .boiler import PARAMS
from .entity import SmartCondensEntity
from .manager import Manager, SmartCondensConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartCondensConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NewPumpSelect(entry.runtime_data)])


class NewPumpSelect(SmartCondensEntity, SelectEntity):
    def __init__(self, manager: Manager) -> None:
        super().__init__(manager, "new_pump")
        self._attr_options = list(PARAMS["pump"].options)

    @property
    def current_option(self) -> str | None:
        return self.manager.boiler.proposed["pump"]

    async def async_select_option(self, option: str) -> None:
        self.manager.boiler.proposed["pump"] = option
        self.manager.boiler.async_cancel()
