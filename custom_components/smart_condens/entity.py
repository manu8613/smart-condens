"""Base entity."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_NAME, DOMAIN
from .manager import Manager


class SmartCondensEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: Manager, key: str, room: str | None = None) -> None:
        self.manager = manager
        self.room_id = room
        owner = manager.entry.entry_id if room is None else room
        self._attr_unique_id = f"{owner}_{key}"
        self._attr_translation_key = key
        name = (
            "Smart Condens"
            if room is None
            else f"Calefacción {manager.rooms[room][CONF_NAME]}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, owner)},
            name=name,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()
