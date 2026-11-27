"""Proposals for the setup wizard, guessed from what Home Assistant already has.

Only generic hints are used: the ebusd entity names, device classes, units, areas and
common Spanish and English words. When two entities fit equally well nothing is
proposed, and nothing is saved without the user seeing it in a form.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import const as c
from . import gastur

EBUSD_RE = re.compile(r"ebusd[_/ .-]*bai[_/ .-]+(.+)$", re.IGNORECASE)


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Words that say what an entity is, not where it is.
_GENERIC = _words(
    "de del la el los las the of temp temperatura temperature sensor sonda termometro "
    "thermometer valvula valve radiador radiator termostato thermostat trv climate "
    "zigbee calefaccion heating planta floor habitacion room"
)
_VALVE_WORDS = _words(
    "valvula valve radiador radiator termostato thermostat trv climate"
)
_NOT_A_ROOM = _words(
    "device chip cpu battery bateria inverter inversor internal interna nevera fridge "
    "freezer congelador agua water outdoor exterior outside calle"
)
_DEMAND_HINTS = ("heating demand", "demand", "demanda", "calefaccion", "heating")
_DEMAND_HINTS += ("position", "posicion", "apertura", "opening")
_NOT_DEMAND = _words("closing cierre limit limite max min battery bateria")
# Their "outside temperature" is an online forecast, not a thermometer.
_ONLINE_WEATHER = frozenset({"tado"})


@dataclass
class _Info:
    entity_id: str
    name: str
    text: str
    tokens: frozenset[str]
    state: State
    device_id: str | None = None
    area_id: str | None = None
    unique_id: str = ""
    platform: str = ""
    auxiliary: bool = False

    def attr(self, key: str) -> Any:
        return self.state.attributes.get(key)

    def has(self, *words: str) -> bool:
        return any(word in self.text for word in words)


@dataclass
class RoomGuess:
    """One heating climate entity and what goes with it."""

    climate: str
    preselected: bool
    data: dict[str, Any] = field(default_factory=dict)


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _places(tokens: frozenset[str]) -> frozenset[str]:
    return frozenset(
        t for t in tokens if t not in _GENERIC and not any(x.isdigit() for x in t)
    )


@callback
def _entities(hass: HomeAssistant, domain: str) -> list[_Info]:
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found = []
    for state in sorted(hass.states.async_all(domain), key=lambda s: s.entity_id):
        entry = entities.async_get(state.entity_id)
        if entry and entry.platform == c.DOMAIN:
            continue
        device = (
            devices.async_get(entry.device_id) if entry and entry.device_id else None
        )
        text = _plain(f"{state.entity_id.split('.', 1)[1]} {state.name}")
        found.append(
            _Info(
                entity_id=state.entity_id,
                name=state.name,
                text=text,
                tokens=frozenset(text.split()),
                state=state,
                device_id=entry.device_id if entry else None,
                area_id=(entry.area_id if entry else None)
                or (device.area_id if device else None),
                unique_id=str(entry.unique_id) if entry else "",
                platform=entry.platform if entry else "",
                auxiliary=bool(entry and (entry.entity_category or entry.hidden_by)),
            )
        )
    return found


def _only(candidates: list[_Info]) -> str | None:
    """An entity is proposed only when there is no doubt."""
    return candidates[0].entity_id if len(candidates) == 1 else None


def _is_temperature(info: _Info) -> bool:
    return info.attr("device_class") == "temperature"


def _ebusd(sensors: list[_Info], *keys: str) -> str | None:
    found: dict[str, str] = {}
    for info in sensors:
        for text in (info.entity_id.split(".", 1)[1], info.unique_id):
            if match := EBUSD_RE.search(text):
                key = re.sub(r"[^a-z0-9]", "", match.group(1).lower())
                found.setdefault(key, info.entity_id)
    return next((found[key] for key in keys if key in found), None)


@callback
def house_suggestions(hass: HomeAssistant) -> dict[str, Any]:
    """Values to pre-fill the first form of the wizard."""
    sensors = _entities(hass, "sensor")
    binaries = _entities(hass, "binary_sensor")
    temperatures = [s for s in sensors if _is_temperature(s) and not s.auxiliary]
    # The probe of an air conditioner's outdoor unit is not the weather either.
    units = {x.device_id for x in _entities(hass, "climate") if x.device_id}
    burners = [b for b in binaries if b.has("quemador", "burner", "llama", "flame")]
    starts = [
        s for s in sensors if s.has("arranques", "starts") and s.has("hora", "hour")
    ]
    gas = [
        s
        for s in sensors
        if "gas" in s.tokens
        and s.attr("device_class") == "energy"
        and s.attr("state_class") in ("total", "total_increasing")
    ]
    guesses = {
        c.CONF_OUTDOOR: _only(
            [
                s
                for s in temperatures
                if s.tokens & {"exterior", "outdoor", "outside", "calle"}
                and s.platform not in _ONLINE_WEATHER
                and s.device_id not in units
            ]
        ),
        c.CONF_FLOW: _ebusd(sensors, "status01temp", "flowtemp")
        or _only(
            [
                s
                for s in temperatures
                if s.has("temperatura ida", "ida caldera", "boiler flow")
            ]
        ),
        c.CONF_RETURN: _ebusd(sensors, "status01temp1", "returntemp")
        or _only(
            [
                s
                for s in temperatures
                if s.has("temperatura retorno", "retorno caldera", "boiler return")
            ]
        ),
        c.CONF_BURNER_HEATING: _only(
            [b for b in burners if b.has("calefaccion", "heating")]
        ),
        c.CONF_BURNER_DHW: _only(
            [b for b in burners if b.has("acs", "dhw", "agua caliente", "hot water")]
        ),
        c.CONF_STARTS: _only(starts)
        or _only([s for s in starts if s.has("calefaccion", "heating")]),
        c.CONF_GAS: gastur.entities(hass).get(gastur.METER)
        or _only(gas)
        or _only([s for s in gas if s.attr("state_class") == "total_increasing"]),
        c.CONF_CHANGE_DATE: dt_util.now().date().isoformat(),
    }
    return {key: value for key, value in guesses.items() if value}


def _room_name(info: _Info, area: str | None) -> str:
    words = [w for w in info.name.split() if _plain(w) not in _VALVE_WORDS]
    name = " ".join(words).strip(" -_·") or area or info.entity_id.split(".", 1)[1]
    return name[:1].upper() + name[1:]


def _room_sensor(climate: _Info, name: str, sensors: list[_Info]) -> str | None:
    """A thermometer of the room: same area first, matching name otherwise."""
    wanted = _places(frozenset(_plain(name).split()))

    def named(info: _Info) -> int:
        places = _places(info.tokens)
        if not wanted or not places or not (wanted <= places or places <= wanted):
            return 0
        return len(wanted & places)

    same_area = [s for s in sensors if climate.area_id and s.area_id == climate.area_id]
    if len(same_area) == 1:
        return same_area[0].entity_id
    pool = same_area or [
        s for s in sensors if not (climate.area_id and s.area_id) and named(s)
    ]
    if not pool:
        return None
    best = max(named(s) for s in pool)
    return _only([s for s in pool if named(s) == best]) if best else None


def _demand(climate: _Info, sensors: list[_Info]) -> str | None:
    """The valve opening or heating percentage published next to the climate."""
    pool = [
        s
        for s in sensors
        if climate.device_id
        and s.device_id == climate.device_id
        and s.attr("unit_of_measurement") == "%"
        and not s.tokens & _NOT_DEMAND
    ]
    for hint in _DEMAND_HINTS:
        if matches := [s for s in pool if s.has(hint)]:
            return _only(matches)
    return None


@callback
def room_guesses(hass: HomeAssistant, house: dict[str, Any]) -> list[RoomGuess]:
    """Every climate entity; the ones that only heat come already selected."""
    climates = _entities(hass, "climate")
    sensors = _entities(hass, "sensor")
    areas = ar.async_get(hass)
    valve_devices = {x.device_id for x in climates if x.device_id}
    used = {house.get(k) for k in (c.CONF_OUTDOOR, c.CONF_FLOW, c.CONF_RETURN)}
    thermometers = [
        s
        for s in sensors
        if _is_temperature(s)
        and not s.auxiliary
        and s.entity_id not in used
        and s.device_id not in valve_devices
        and not s.tokens & _NOT_A_ROOM
    ]
    guesses: list[RoomGuess] = []
    names: set[str] = set()
    for climate in climates:
        modes = climate.attr("hvac_modes") or []
        heating = "cool" not in modes and ("heat" in modes or "auto" in modes)
        area = areas.async_get_area(climate.area_id) if climate.area_id else None
        base = name = _room_name(climate, area.name if area else None)
        number = 2
        repeated = name.casefold() in names
        while name.casefold() in names:
            name = f"{base} {number}"
            number += 1
        names.add(name.casefold())
        data = {c.CONF_NAME: name, c.CONF_CLIMATE: climate.entity_id}
        if sensor := _room_sensor(climate, base, thermometers):
            data[c.CONF_TEMP] = sensor
        if demand := _demand(climate, sensors):
            data[c.CONF_DEMAND] = demand
        guesses.append(
            RoomGuess(
                climate=climate.entity_id,
                preselected=heating and not repeated and not climate.auxiliary,
                data=data,
            )
        )
    return guesses
