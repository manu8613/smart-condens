"""The wizard proposes entities and rooms, and creates what the user accepts."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_condens import const as c
from custom_components.smart_condens import detect

TEMP = {"device_class": "temperature", "unit_of_measurement": "°C"}
PERCENT = {"unit_of_measurement": "%"}
GAS = {"device_class": "energy", "state_class": "total_increasing"}
HEAT = {"hvac_modes": ["off", "heat", "auto"]}
AC = {"hvac_modes": ["off", "heat", "cool"]}


class House:
    """A made-up installation, registered like real integrations do it."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.source = MockConfigEntry(domain="test")
        self.source.add_to_hass(hass)

    def device(self, name: str, area: str | None = None) -> str:
        devices = dr.async_get(self.hass)
        device = devices.async_get_or_create(
            config_entry_id=self.source.entry_id, identifiers={("test", name)}
        )
        if area:
            area_id = ar.async_get(self.hass).async_get_or_create(area).id
            devices.async_update_device(device.id, area_id=area_id)
        return device.id

    def add(
        self,
        entity_id: str,
        attrs: dict | None = None,
        device: str | None = None,
        name: str | None = None,
        platform: str = "mqtt",
        **registry,
    ) -> str:
        domain, object_id = entity_id.split(".")
        er.async_get(self.hass).async_get_or_create(
            domain,
            platform,
            registry.pop("unique_id", object_id),
            suggested_object_id=object_id,
            device_id=device,
            **registry,
        )
        attributes = dict(attrs or {})
        if name:
            attributes["friendly_name"] = name
        self.hass.states.async_set(entity_id, "20", attributes)
        return entity_id


def build(hass) -> None:
    house = House(hass)
    boiler = house.device("boiler")
    house.add("sensor.boiler_ebusd_bai_status01_temp", TEMP, boiler)
    house.add("sensor.boiler_ebusd_bai_status01_temp_1", TEMP, boiler)
    house.add("sensor.boiler_ebusd_bai_status01_temp_3", TEMP, boiler)
    house.add("binary_sensor.boiler_burner_heating")
    house.add("binary_sensor.boiler_burner_dhw")
    house.add("sensor.boiler_heating_starts_last_hour")
    house.add("sensor.gas_energy", GAS)
    house.add("sensor.station_outdoor_temperature", TEMP)
    house.add("sensor.home_outside_temperature", TEMP, platform="tado")

    # A cloud thermostat zone: its own thermometer is on the valve.
    zone = house.device("zone", "Desván")
    house.add("climate.desvan", HEAT, zone, "Desván", "tado")
    house.add("sensor.desvan_temperature", TEMP, zone, platform="tado")
    house.add("sensor.desvan_heating", PERCENT, zone, "Desván Heating", "tado")
    house.add("sensor.desvan_humidity", PERCENT, zone, platform="tado")
    probe = house.device("probe", "Desván")
    house.add("sensor.temperature_0a1b2c", TEMP, probe)
    house.add(
        "sensor.probe_chip",
        TEMP,
        probe,
        entity_category=er.EntityCategory.DIAGNOSTIC,
    )

    # A Zigbee valve without area: matched with the thermometer by name.
    pantry = house.device("despensa_valve")
    house.add("climate.despensa", HEAT, pantry, "Válvula Despensa")
    house.add("sensor.despensa_valve_local", TEMP, pantry, "Válvula Despensa local")
    house.add("sensor.despensa_valve_position", PERCENT, pantry)
    house.add("sensor.despensa_valve_closing_position", PERCENT, pantry)
    house.add("sensor.temp_despensa", TEMP, name="Temperatura Despensa")

    # A bathroom with nothing but the valve: another bedroom must not be borrowed.
    house.add("climate.bath", HEAT, name="Aseo norte")
    house.add("sensor.temp_cuarto_norte", TEMP, name="Cuarto norte")

    # Air conditioning is listed but not selected.
    unit = house.device("air")
    house.add("climate.air", AC, unit, "Aire desván")
    house.add("sensor.air_outdoor_temperature", TEMP, unit)


async def test_house_suggestions(hass):
    build(hass)
    assert detect.house_suggestions(hass) == {
        c.CONF_OUTDOOR: "sensor.station_outdoor_temperature",
        c.CONF_FLOW: "sensor.boiler_ebusd_bai_status01_temp",
        c.CONF_RETURN: "sensor.boiler_ebusd_bai_status01_temp_1",
        c.CONF_BURNER_HEATING: "binary_sensor.boiler_burner_heating",
        c.CONF_BURNER_DHW: "binary_sensor.boiler_burner_dhw",
        c.CONF_STARTS: "sensor.boiler_heating_starts_last_hour",
        c.CONF_GAS: "sensor.gas_energy",
        c.CONF_CHANGE_DATE: dt_util.now().date().isoformat(),
    }


async def test_doubtful_entities_are_not_proposed(hass):
    house = House(hass)
    house.add("sensor.outdoor_north", TEMP)
    house.add("sensor.outdoor_south", TEMP)
    house.add("sensor.gas_one", GAS)
    house.add("sensor.gas_two", GAS)
    assert list(detect.house_suggestions(hass)) == [c.CONF_CHANGE_DATE]


async def test_room_guesses(hass):
    build(hass)
    guesses = {g.climate: g for g in detect.room_guesses(hass, {})}
    assert guesses["climate.desvan"].data == {
        c.CONF_NAME: "Desván",
        c.CONF_CLIMATE: "climate.desvan",
        c.CONF_TEMP: "sensor.temperature_0a1b2c",
        c.CONF_DEMAND: "sensor.desvan_heating",
    }
    assert guesses["climate.despensa"].data == {
        c.CONF_NAME: "Despensa",
        c.CONF_CLIMATE: "climate.despensa",
        c.CONF_TEMP: "sensor.temp_despensa",
        c.CONF_DEMAND: "sensor.despensa_valve_position",
    }
    assert guesses["climate.bath"].data == {
        c.CONF_NAME: "Aseo norte",
        c.CONF_CLIMATE: "climate.bath",
    }
    assert [g.climate for g in guesses.values() if not g.preselected] == ["climate.air"]


async def test_wizard_creates_the_rooms(hass):
    build(hass)
    result = await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": SOURCE_USER}
    )
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[c.CONF_FLOW] == "sensor.boiler_ebusd_bai_status01_temp"
    house = {
        key: suggested[key]
        for key in (c.CONF_OUTDOOR, c.CONF_FLOW, c.CONF_RETURN, c.CONF_GAS)
    }
    configure = hass.config_entries.flow.async_configure
    result = await configure(result["flow_id"], house)
    assert result["step_id"] == "rooms"

    result = await configure(
        result["flow_id"],
        {c.CONF_ROOMS: ["climate.desvan", "climate.despensa"]},
    )
    assert result["step_id"] == "room"
    assert result["description_placeholders"]["current"] == "1"
    assert result["description_placeholders"]["total"] == "2"

    # Rooms come in entity id order: despensa first.
    result = await configure(
        result["flow_id"],
        {
            c.CONF_NAME: "Despensa",
            c.CONF_TEMP: "sensor.temp_despensa",
            c.CONF_ELEMENTS: 6,
        },
    )
    assert result["description_placeholders"]["current"] == "2"
    result = await configure(result["flow_id"], {c.CONF_NAME: "despensa"})
    assert result["errors"] == {c.CONF_NAME: "duplicate_name"}
    result = await configure(result["flow_id"], {c.CONF_NAME: "{}"})
    assert result["errors"] == {c.CONF_NAME: "empty_name"}
    # The proposed sensor can be cleared: the valve temperature is then used.
    result = await configure(result["flow_id"], {c.CONF_NAME: "Desván"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = result["result"]
    rooms = {s.title: dict(s.data) for s in entry.subentries.values()}
    assert rooms["Despensa"][c.CONF_CLIMATE] == "climate.despensa"
    assert rooms["Despensa"][c.CONF_ELEMENTS] == 6
    assert rooms["Desván"][c.CONF_CLIMATE] == "climate.desvan"
    assert c.CONF_TEMP not in rooms["Desván"]
    assert len(entry.runtime_data.rooms) == 2


async def test_wizard_without_rooms(hass):
    build(hass)
    result = await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": SOURCE_USER}
    )
    configure = hass.config_entries.flow.async_configure
    result = await configure(
        result["flow_id"],
        {
            c.CONF_OUTDOOR: "sensor.station_outdoor_temperature",
            c.CONF_FLOW: "sensor.boiler_ebusd_bai_status01_temp",
            c.CONF_RETURN: "sensor.boiler_ebusd_bai_status01_temp_1",
        },
    )
    result = await configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not result["result"].subentries
    await hass.async_block_till_done()
