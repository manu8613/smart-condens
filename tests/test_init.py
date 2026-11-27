"""Setup, config flows, entities, dashboard and gas statistics."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.smart_condens import const as c
from custom_components.smart_condens.dashboard import panel_path
from custom_components.smart_condens.manager import statistic_id

from .conftest import HOUSE, make_entry, set_house


async def _setup(hass, entry):
    assert await async_setup_component(hass, "lovelace", {})
    set_house(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _entity(hass, entry, platform, key, room=None):
    owner = entry.entry_id
    if room:
        owner = next(
            s.subentry_id for s in entry.subentries.values() if s.title == room
        )
    found = er.async_get(hass).async_get_entity_id(platform, c.DOMAIN, f"{owner}_{key}")
    assert found, key
    return found


async def test_flows(hass):
    result = await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**HOUSE, c.CONF_MQTT_TOPIC: "bad topic#"}
    )
    assert result["errors"] == {c.CONF_MQTT_TOPIC: "invalid_topic"}
    house = {k: v for k, v in HOUSE.items() if k != c.CONF_ALLOW_WRITE}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], house)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data[c.CONF_ALLOW_WRITE] is False  # writing is opt-in
    await hass.async_block_till_done()

    async def add(name):
        flow = await hass.config_entries.subentries.async_init(
            (entry.entry_id, c.SUBENTRY_ROOM), context={"source": SOURCE_USER}
        )
        return await hass.config_entries.subentries.async_configure(
            flow["flow_id"], {c.CONF_NAME: name, c.CONF_CLIMATE: "climate.valve_a"}
        )

    assert (await add("Hall {{ x }} |"))["title"] == "Hall  x"
    await hass.async_block_till_done()
    assert (await add("hall  x"))["errors"] == {c.CONF_NAME: "duplicate_name"}

    # Clearing an optional field in the options really removes it.
    options = await hass.config_entries.options.async_init(entry.entry_id)
    new = {k: v for k, v in house.items() if k != c.CONF_GAS}
    await hass.config_entries.options.async_configure(options["flow_id"], new)
    await hass.async_block_till_done()
    assert c.CONF_GAS not in entry.runtime_data.cfg


async def test_entities_use_room_sensor_or_valve(hass):
    entry = make_entry()
    manager = await _setup(hass, entry)
    get = lambda key, room=None: hass.states.get(
        _entity(hass, entry, "sensor", key, room)
    )
    assert get("temperature", "Room A").state == "19.0"
    assert get("offset", "Room A").state == "2.0"
    assert get("advice", "Room A").attributes["source"] == "sonda"
    assert get("temperature", "Room B").state == "20.0"
    assert get("advice", "Room B").attributes["source"] == "válvula"
    assert get("offset", "Room B").state == "unknown"
    assert get("delta").state == "10.0"
    assert int(get("power", "Room A").state) > 0
    assert get("recommendation").state == "Reuniendo datos"
    assert get("boiler_pending").state == "none"

    # A configured room sensor that dies is not replaced by the valve.
    hass.states.async_set("sensor.room_a", "unavailable")
    await hass.async_block_till_done()
    assert get("temperature", "Room A").state == "unknown"
    assert get("valve", "Room A").state == "Sin datos"
    assert manager.state


async def test_dashboard_only_refers_to_real_entities(hass):
    entry = make_entry()
    await _setup(hass, entry)
    panel = await hass.async_add_executor_job(load_yaml_dict, str(panel_path(hass)))
    assert [v["path"] for v in panel["views"]] == ["hoy", "ondas", "gas", "caldera"]
    assert "smart-condens" in hass.data["lovelace"].dashboards

    own = {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    confirmations = []
    confirm_id = _entity(hass, entry, "button", "confirm_change")

    def walk(node):
        if isinstance(node, dict):
            action = node.get("tap_action", {})
            if action.get("target", {}).get("entity_id") == confirm_id:
                confirmations.append(action.get("confirmation"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif (
            isinstance(node, str)
            and node.split(".")[0] in ("sensor", "button", "number", "select")
            and "." in node
            and " " not in node
            and node != "button.press"
        ):
            assert node in own or hass.states.get(node), node

    walk(panel)
    assert confirmations and all(confirmations)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "smart-condens" not in hass.data["lovelace"].dashboards


async def test_gas_before_and_after(hass):
    today = dt_util.now().date()
    changed = today - timedelta(days=6)
    for statistic, unit, unit_class, has_sum in (
        ("sensor.gas", "kWh", "energy", True),
        ("sensor.outdoor", "°C", "temperature", False),
    ):
        points, total = [], 0.0
        for back in range(20, 0, -1):
            day = today - timedelta(days=back)
            start = dt_util.as_utc(dt_util.start_of_local_day(day))
            if has_sum:
                total += 40 if day < changed else 36
                points.append(StatisticData(start=start, state=total, sum=total))
            else:
                points.append(StatisticData(start=start, mean=8, min=8, max=8))
        async_import_statistics(
            hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE
                if has_sum
                else StatisticMeanType.ARITHMETIC,
                has_sum=has_sum,
                name=None,
                source="recorder",
                statistic_id=statistic,
                unit_class=unit_class,
                unit_of_measurement=unit,
            ),
            points,
        )
    await async_wait_recording_done(hass)
    entry = make_entry(**{c.CONF_CHANGE_DATE: changed.isoformat()})
    manager = await _setup(hass, entry)
    await manager.async_update_gas()
    await async_wait_recording_done(hass)
    assert (manager.gas["before"], manager.gas["after"]) == (4.0, 3.6)
    assert manager.gas["saving_pct"] == 10.0
    state = hass.states.get(_entity(hass, entry, "sensor", "gas_saving"))
    assert state.state == "10.0"
    series = statistic_id(entry, "diff")
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utcnow() - timedelta(days=30),
        None,
        {series},
        "day",
        None,
        {"change"},
    )
    assert round(stats[series][-1]["change"], 2) == -0.28
