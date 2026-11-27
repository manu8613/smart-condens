"""Reads the user's entities, keeps the history and computes the indicators."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import calc
from . import const as c
from .boiler import Boiler

_LOGGER = logging.getLogger(__name__)

type SmartCondensConfigEntry = ConfigEntry[Manager]

EXTERNAL_SERIES = {
    "cost": ("Coste diario de gas", "EUR"),
    "diff": ("Gas: más (+) o menos (−) que antes", "EUR"),
    "heat": ("Gas de calefacción por día", "kWh"),
}


def settings(entry: ConfigEntry) -> dict[str, Any]:
    """The options form is complete, so once saved it replaces the first setup."""
    return dict(entry.options or entry.data)


def statistic_id(entry: ConfigEntry, series: str) -> str:
    return f"{c.DOMAIN}:{entry.entry_id.lower()}_{series}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if -1e12 < number < 1e12 else None


@dataclass
class RoomValues:
    temp: float | None
    source: str
    target: float | None
    demand: float | None
    valve_temp: float | None
    offset: float | None
    valve: str
    watts: int | None
    advice: str


class Manager:
    def __init__(self, hass: HomeAssistant, entry: SmartCondensConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg = settings(entry)
        self.rooms: dict[str, dict[str, Any]] = {
            sid: dict(sub.data)
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == c.SUBENTRY_ROOM
        }
        self.state: dict[str, calc.RoomState] = {}
        self.returns: list[list[float]] = []
        self.flow_set = c.DEFAULT_FLOW_SET
        self.gas: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []
        self._store: Store[dict[str, Any]] = Store(
            hass, c.STORAGE_VERSION, f"{c.DOMAIN}.{entry.entry_id}"
        )
        self.boiler = Boiler(
            hass,
            self.cfg.get(c.CONF_MQTT_TOPIC) or "ebusd",
            self.cfg.get(c.CONF_CIRCUIT) or "bai",
            bool(self.cfg.get(c.CONF_ALLOW_WRITE)),
            self.async_notify,
        )

    # --- storage and listeners -------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        saved = data.get("rooms", {})
        self.state = {
            sid: calc.RoomState.from_dict(saved.get(sid)) for sid in self.rooms
        }
        self.returns = data.get("returns", [])
        self.flow_set = data.get("flow_set", c.DEFAULT_FLOW_SET)
        self.boiler.log = data.get("boiler_log", [])

    def _data(self) -> dict[str, Any]:
        return {
            "rooms": {sid: s.as_dict() for sid, s in self.state.items()},
            "returns": self.returns,
            "flow_set": self.flow_set,
            "boiler_log": self.boiler.log,
        }

    async def async_save(self) -> None:
        await self._store.async_save(self._data())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_schedule_save(self) -> None:
        self._store.async_delay_save(self._data, 10)

    @callback
    def async_start(self) -> None:
        watched = {
            self.cfg.get(key)
            for key in (
                c.CONF_OUTDOOR,
                c.CONF_FLOW,
                c.CONF_RETURN,
                c.CONF_BURNER_HEATING,
                c.CONF_BURNER_DHW,
                c.CONF_STARTS,
            )
        }
        for room in self.rooms.values():
            watched |= {
                room.get(c.CONF_TEMP),
                room.get(c.CONF_CLIMATE),
                room.get(c.CONF_DEMAND),
            }
        unload = self.entry.async_on_unload
        unload(
            async_track_state_change_event(
                self.hass, [e for e in watched if e], self._changed
            )
        )
        unload(async_track_time_change(self.hass, self._hourly, minute=0, second=10))
        unload(
            async_track_time_interval(
                self.hass, self._five_minutes, timedelta(minutes=5)
            )
        )
        for hour, minute in ((0, 20), (6, 0)):
            unload(
                async_track_time_change(
                    self.hass, self._daily, hour=hour, minute=minute, second=0
                )
            )

    # --- reading entities ------------------------------------------------------
    def value(self, key: str) -> float | None:
        entity_id = self.cfg.get(key)
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        return _number(state.state)

    def is_on(self, key: str) -> bool:
        entity_id = self.cfg.get(key)
        return bool(entity_id) and self.hass.states.is_state(entity_id, "on")

    def _demand(self, room: dict[str, Any]) -> float | None:
        """0 = not asking for heat, >0 asking (percentage if known)."""
        climate = self.hass.states.get(room[c.CONF_CLIMATE])
        if climate is None or climate.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        if entity_id := room.get(c.CONF_DEMAND):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return None
            if (number := _number(state.state)) is not None:
                return max(number, 0.0)
            return 100.0 if state.state in ("on", "heat", "heating", "open") else 0.0
        if (position := _number(climate.attributes.get("position"))) is not None:
            return max(position, 0.0)
        action = climate.attributes.get("hvac_action")
        if action is None:
            return None
        return 100.0 if action == "heating" else 0.0

    def _readings(
        self, room: dict[str, Any]
    ) -> tuple[float | None, str, float | None, float | None, float | None]:
        climate = self.hass.states.get(room[c.CONF_CLIMATE])
        attrs = climate.attributes if climate else {}
        usable = climate is not None and climate.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )
        valve_temp = _number(attrs.get("current_temperature")) if usable else None
        target = _number(attrs.get("temperature")) if usable else None
        if usable and climate.state == "off":
            target = None
        if entity_id := room.get(c.CONF_TEMP):
            # A configured sensor is never silently replaced by the valve.
            state = self.hass.states.get(entity_id)
            temp = _number(state.state) if state else None
            source = "sonda"
        else:
            temp, source = valve_temp, "válvula"
        return temp, source, target, self._demand(room), valve_temp

    def room(self, sid: str) -> RoomValues:
        room = self.rooms[sid]
        state = self.state[sid]
        temp, source, target, demand, valve_temp = self._readings(room)
        flow, ret = self.value(c.CONF_FLOW), self.value(c.CONF_RETURN)
        hot = calc.circulating(flow, temp, self.is_on(c.CONF_BURNER_DHW))
        minutes = (
            0.0
            if state.open_since is None
            else (dt_util.utcnow().timestamp() - state.open_since) / 60
        )
        loop = max(
            (int(r.get(c.CONF_ORDER) or 0) for r in self.rooms.values()), default=0
        )
        offset = None
        if source == "sonda" and temp is not None and valve_temp is not None:
            offset = round(valve_temp - temp, 1)
        return RoomValues(
            temp=temp,
            source=source,
            target=target,
            demand=demand,
            valve_temp=valve_temp,
            offset=offset,
            valve=calc.valve_state(temp, target, demand, hot, minutes, state.rate),
            watts=calc.radiator_watts(
                float(room.get(c.CONF_ELEMENTS) or 0),
                float(self.cfg.get(c.CONF_W_ELEMENT) or c.DEFAULT_W_ELEMENT),
                int(room.get(c.CONF_ORDER) or 0),
                loop,
                flow,
                ret,
                temp,
                demand,
                hot,
            ),
            advice=calc.room_advice(state, temp, target, demand, valve_temp),
        )

    @property
    def return_average(self) -> float | None:
        limit = dt_util.utcnow().timestamp() - 86400
        values = [v for ts, v in self.returns if ts >= limit]
        return round(sum(values) / len(values), 1) if values else None

    @property
    def change_date(self) -> date | None:
        return dt_util.parse_date(self.cfg.get(c.CONF_CHANGE_DATE) or "")

    @property
    def recommendation(self) -> tuple[str, str]:
        changed = self.change_date
        days = None if changed is None else (dt_util.now().date() - changed).days
        return calc.recommendation(
            {r[c.CONF_NAME]: self.state[sid] for sid, r in self.rooms.items()},
            self.flow_set,
            days,
            self.return_average,
            self.value(c.CONF_STARTS),
        )

    # --- periodic work ---------------------------------------------------------
    @callback
    def async_track_demand(self) -> None:
        now = dt_util.utcnow().timestamp()
        for sid, room in self.rooms.items():
            demand = self._demand(room)
            if demand is None or demand <= 0:
                self.state[sid].open_since = None
            elif self.state[sid].open_since is None:
                self.state[sid].open_since = now

    @callback
    def async_sample(self) -> None:
        now = dt_util.utcnow().timestamp()
        outdoor = self.value(c.CONF_OUTDOOR)
        for sid, room in self.rooms.items():
            temp, _, target, demand, _ = self._readings(room)
            calc.sample_room(self.state[sid], now, temp, target, demand, outdoor)

    @callback
    def _changed(self, _event: Any) -> None:
        self.async_track_demand()
        self.async_notify()

    @callback
    def _hourly(self, _now: datetime) -> None:
        self.async_sample()
        self.async_notify()
        self.async_schedule_save()

    @callback
    def _five_minutes(self, _now: datetime) -> None:
        ret = self.value(c.CONF_RETURN)
        if self.cfg.get(c.CONF_BURNER_HEATING):
            heating = self.is_on(c.CONF_BURNER_HEATING)
        else:
            flow = self.value(c.CONF_FLOW)
            heating = flow is not None and flow >= 30
        heating = heating and not self.is_on(c.CONF_BURNER_DHW)
        now = dt_util.utcnow().timestamp()
        self.returns = [r for r in self.returns if r[0] >= now - 86400]
        if heating and ret is not None:
            self.returns.append([now, ret])
        self.async_notify()
        self.async_schedule_save()

    async def _daily(self, _now: datetime) -> None:
        await self.async_update_gas()

    async def async_recalculate(self) -> None:
        self.async_track_demand()
        self.async_sample()
        await self.async_update_gas()

    # --- gas -------------------------------------------------------------------
    async def _statistics(
        self, start: date, end: date, ids: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        return await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            dt_util.as_utc(dt_util.start_of_local_day(start)),
            dt_util.as_utc(dt_util.start_of_local_day(end)),
            ids,
            "day",
            {"energy": "kWh", "temperature": "°C"},
            {"change", "mean"},
        )

    async def async_update_gas(self) -> None:
        gas_id = self.cfg.get(c.CONF_GAS)
        outdoor_id = self.cfg.get(c.CONF_OUTDOOR)
        changed = self.change_date
        if not gas_id or not outdoor_id or changed is None:
            self.gas = {}
            self.async_notify()
            return
        today = dt_util.now().date()
        summer_start, summer_end = calc.previous_summer(today)
        try:
            stats = await self._statistics(
                changed - timedelta(days=21),
                max(today, changed - timedelta(days=20)),
                {gas_id, outdoor_id},
            )
            summer = await self._statistics(summer_start, summer_end, {gas_id})
        except Exception:
            _LOGGER.exception("No se han podido leer las estadísticas de gas")
            return

        def by_day(rows: list[dict[str, Any]], key: str) -> dict[date, float]:
            return {
                dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date(): row[
                    key
                ]
                for row in rows
                if row.get(key) is not None
            }

        gas = by_day(stats.get(gas_id, []), "change")
        outdoor = by_day(stats.get(outdoor_id, []), "mean")
        dhw, dhw_ok = calc.dhw_baseline(
            list(by_day(summer.get(gas_id, []), "change").values()),
            float(self.cfg.get(c.CONF_DHW_BASE) or 0),
        )
        summary = calc.gas_summary(
            [(day, gas[day], outdoor[day]) for day in gas if day in outdoor],
            changed,
            float(self.cfg.get(c.CONF_GD_BASE) or c.DEFAULT_GD_BASE),
            dhw,
            float(self.cfg.get(c.CONF_PRICE) or 0),
            today,
        )
        summary["dhw"] = round(dhw, 1)
        summary["dhw_ok"] = dhw_ok
        self.gas = summary
        self._publish_series(summary["rows"])
        self.async_notify()

    def _publish_series(self, rows: list[dict[str, Any]]) -> None:
        """Daily series as external statistics, so native graphs can draw them."""
        for series, (name, unit) in EXTERNAL_SERIES.items():
            total = 0.0
            points: list[StatisticData] = []
            for row in rows:
                if series != "heat" and row["cost"] is None:
                    continue
                value = row[series] or 0.0
                total += value
                points.append(
                    StatisticData(
                        start=dt_util.as_utc(dt_util.start_of_local_day(row["date"])),
                        state=round(value, 3),
                        sum=round(total, 3),
                    )
                )
            if not points:
                continue
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=name,
                    source=c.DOMAIN,
                    statistic_id=statistic_id(self.entry, series),
                    unit_class="energy" if unit == "kWh" else None,
                    unit_of_measurement=unit,
                ),
                points,
            )
