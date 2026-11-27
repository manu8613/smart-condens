"""Numbers: the flow temperature the user has set, and the proposed new limit."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
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
    manager = entry.runtime_data
    async_add_entities([FlowSetNumber(manager), NewFlowMaxNumber(manager)])


class FlowSetNumber(SmartCondensEntity, NumberEntity):
    """A note of what is set on the boiler. Changing it sends nothing."""

    _attr_native_min_value = 30
    _attr_native_max_value = 80
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, manager: Manager) -> None:
        super().__init__(manager, "flow_set")

    @property
    def native_value(self) -> float:
        return self.manager.flow_set

    async def async_set_native_value(self, value: float) -> None:
        self.manager.flow_set = value
        self.manager.async_notify()
        self.manager.async_schedule_save()


class NewFlowMaxNumber(SmartCondensEntity, NumberEntity):
    """Proposed value only: it is not sent until prepared and confirmed."""

    _attr_native_min_value = PARAMS["flow_max"].minimum
    _attr_native_max_value = PARAMS["flow_max"].maximum
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, manager: Manager) -> None:
        super().__init__(manager, "new_flow_max")

    @property
    def native_value(self) -> float | None:
        value = self.manager.boiler.proposed["flow_max"]
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        self.manager.boiler.proposed["flow_max"] = f"{value:g}"
        # A different proposal invalidates what was prepared.
        self.manager.boiler.async_cancel()
