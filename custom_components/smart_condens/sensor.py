"""Sensors: one set for the house and one per room."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import calc
from . import const as c
from .entity import SmartCondensEntity
from .manager import Manager, SmartCondensConfigEntry

MEASUREMENT = SensorStateClass.MEASUREMENT
CELSIUS = UnitOfTemperature.CELSIUS


@dataclass(frozen=True, kw_only=True)
class Description(SensorEntityDescription):
    value: Callable[..., Any]
    extra: Callable[..., dict[str, Any]] | None = None


def _gas_attrs(m: Manager) -> dict[str, Any]:
    data = {k: v for k, v in m.gas.items() if k != "rows"}
    data["rows"] = [
        {
            "date": row["date"].isoformat(),
            "period": row["period"],
            "gas": round(row["gas"], 1),
            "outdoor": round(row["outdoor"], 1),
            "ratio": None if row["ratio"] is None else round(row["ratio"], 2),
            "diff": None if row["diff"] is None else round(row["diff"], 2),
        }
        for row in m.gas.get("rows", [])[-21:]
    ]
    return data


def _delta(m: Manager) -> float | None:
    flow, ret = m.value(c.CONF_FLOW), m.value(c.CONF_RETURN)
    return None if flow is None or ret is None else round(flow - ret, 1)


HOUSE: tuple[Description, ...] = (
    Description(
        key="recommendation",
        value=lambda m: m.recommendation[0],
        extra=lambda m: {"reason": m.recommendation[1]},
    ),
    Description(
        key="return_average",
        value=lambda m: m.return_average,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=CELSIUS,
        state_class=MEASUREMENT,
    ),
    Description(
        key="delta",
        value=_delta,
        native_unit_of_measurement=CELSIUS,
        state_class=MEASUREMENT,
    ),
    Description(
        key="gas_saving",
        value=lambda m: m.gas.get("saving_pct"),
        extra=_gas_attrs,
        native_unit_of_measurement=PERCENTAGE,
    ),
    Description(key="boiler_flow_max", value=lambda m: m.boiler.values["flow_max"]),
    Description(key="boiler_pump", value=lambda m: m.boiler.values["pump"]),
    Description(
        key="boiler_pending",
        value=lambda m: "pending" if m.boiler.pending else "none",
        extra=lambda m: {"warning": m.boiler.warning},
        device_class=SensorDeviceClass.ENUM,
        options=["none", "pending"],
    ),
    Description(
        key="boiler_status",
        value=lambda m: m.boiler.status[:255],
        extra=lambda m: {"log": list(m.boiler.log)},
    ),
)

# Room values receive the manager and the room id.
ROOM: tuple[Description, ...] = (
    Description(
        key="advice",
        value=lambda m, r: m.room(r).advice,
        extra=lambda m, r: {
            "source": m.room(r).source,
            "target": m.room(r).target,
            "demand": m.room(r).demand,
            "valve_temperature": m.room(r).valve_temp,
            "unmet_hours": m.state[r].unmet_run,
        },
    ),
    Description(
        key="temperature",
        value=lambda m, r: m.room(r).temp,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=CELSIUS,
        state_class=MEASUREMENT,
    ),
    Description(
        key="offset",
        value=lambda m, r: m.room(r).offset,
        native_unit_of_measurement=CELSIUS,
        state_class=MEASUREMENT,
    ),
    Description(key="valve", value=lambda m, r: m.room(r).valve),
    Description(
        key="power",
        value=lambda m, r: m.room(r).watts,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=MEASUREMENT,
    ),
    Description(
        key="heating_rate",
        value=lambda m, r: m.state[r].heating,
        native_unit_of_measurement="°C/h",
    ),
    Description(
        key="cooling_rate",
        value=lambda m, r: m.state[r].cooling,
        native_unit_of_measurement="°C/h",
    ),
    Description(
        key="inertia",
        value=lambda m, r: calc.inertia_label(m.state[r]),
        extra=lambda m, r: {
            "hours": m.state[r].inertia,
            "samples": m.state[r].cool_samples,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartCondensConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(SmartCondensSensor(manager, d) for d in HOUSE)
    for room in manager.rooms:
        async_add_entities(
            [SmartCondensSensor(manager, d, room) for d in ROOM],
            config_subentry_id=room,
        )


class SmartCondensSensor(SmartCondensEntity, SensorEntity):
    entity_description: Description

    def __init__(
        self, manager: Manager, description: Description, room: str | None = None
    ) -> None:
        super().__init__(manager, description.key, room)
        self.entity_description = description

    def _args(self) -> tuple[Any, ...]:
        return (self.manager,) if self.room_id is None else (self.manager, self.room_id)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(*self._args())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        extra = self.entity_description.extra
        return None if extra is None else extra(*self._args())
