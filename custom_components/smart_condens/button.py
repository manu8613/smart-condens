"""Buttons: recalculate and the boiler change steps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SmartCondensEntity
from .manager import Manager, SmartCondensConfigEntry


async def _cancel(manager: Manager) -> None:
    manager.boiler.async_cancel()


async def _recalculate(manager: Manager) -> None:
    await manager.async_recalculate()


ACTIONS: dict[str, Callable[[Manager], Awaitable[None]]] = {
    "recalculate": _recalculate,
    "read_boiler": lambda m: m.boiler.async_refresh(),
    "prepare_flow_max": lambda m: m.boiler.async_prepare("flow_max"),
    "prepare_pump": lambda m: m.boiler.async_prepare("pump"),
    "confirm_change": lambda m: m.boiler.async_confirm(),
    "cancel_change": _cancel,
}
# Only an administrator, by hand, may do these: no automations.
ADMIN_ONLY = {"prepare_flow_max", "prepare_pump", "confirm_change"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartCondensConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(ActionButton(entry.runtime_data, key) for key in ACTIONS)


class ActionButton(SmartCondensEntity, ButtonEntity):
    def __init__(self, manager: Manager, key: str) -> None:
        super().__init__(manager, key)
        self._key = key

    async def async_press(self) -> None:
        if self._key in ADMIN_ONLY:
            user_id = self._context.user_id if self._context else None
            user = await self.hass.auth.async_get_user(user_id) if user_id else None
            if user is None or not user.is_admin:
                raise HomeAssistantError(
                    "Los cambios en la caldera solo los puede hacer a mano "
                    "un administrador"
                )
        await ACTIONS[self._key](self.manager)
