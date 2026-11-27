"""Shared fixtures: a made-up house and a fake ebusd answering over MQTT."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.smart_condens import boiler
from custom_components.smart_condens import const as c

HOUSE = {
    c.CONF_OUTDOOR: "sensor.outdoor",
    c.CONF_FLOW: "sensor.flow",
    c.CONF_RETURN: "sensor.return",
    c.CONF_BURNER_HEATING: "binary_sensor.burner",
    c.CONF_BURNER_DHW: "binary_sensor.dhw",
    c.CONF_STARTS: "sensor.starts",
    c.CONF_GAS: "sensor.gas",
    c.CONF_PRICE: 0.07,
    c.CONF_CHANGE_DATE: "2026-11-10",
    c.CONF_ALLOW_WRITE: True,
}


@pytest.fixture
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder must exist before the integration is loaded."""


@pytest.fixture(autouse=True)
def _enable(auto_enable_custom_integrations):
    """Enable custom integrations everywhere."""


def set_house(hass) -> None:
    for entity_id, value in (
        ("sensor.outdoor", "8"),
        ("sensor.flow", "60"),
        ("sensor.return", "50"),
        ("binary_sensor.burner", "on"),
        ("binary_sensor.dhw", "off"),
        ("sensor.starts", "1"),
        ("sensor.gas", "100"),
        ("sensor.room_a", "19.0"),
        ("sensor.demand_a", "40"),
    ):
        hass.states.async_set(entity_id, value)
    hass.states.async_set(
        "climate.valve_a", "heat", {"current_temperature": 21.0, "temperature": 21}
    )
    hass.states.async_set(
        "climate.valve_b",
        "heat",
        {"current_temperature": 20.0, "temperature": 21, "position": 60},
    )


def make_entry(**changes) -> MockConfigEntry:
    return MockConfigEntry(
        domain=c.DOMAIN,
        title="Smart Condens",
        data={**HOUSE, **changes},
        subentries_data=[
            {
                "subentry_type": c.SUBENTRY_ROOM,
                "title": "Room A",
                "unique_id": None,
                "data": {
                    c.CONF_NAME: "Room A",
                    c.CONF_CLIMATE: "climate.valve_a",
                    c.CONF_TEMP: "sensor.room_a",
                    c.CONF_DEMAND: "sensor.demand_a",
                    c.CONF_ELEMENTS: 8,
                    c.CONF_ORDER: 1,
                },
            },
            {
                "subentry_type": c.SUBENTRY_ROOM,
                "title": "Room B",
                "unique_id": None,
                "data": {c.CONF_NAME: "Room B", c.CONF_CLIMATE: "climate.valve_b"},
            },
        ],
    )


class FakeEbusd:
    """Answers like ebusd: reads from its registers, echoes accepted writes."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.registers = {"FlowsetHcMax": "65", "PumpPowerDesired": "70"}
        self.sent: list[tuple[str, str]] = []
        self.ignore_writes = False
        self.silent = False

    async def publish(self, hass, topic, payload, *args, **kwargs) -> None:
        self.sent.append((topic, payload))
        base, action = topic.rsplit("/", 1)
        name = base.rsplit("/", 1)[1]
        if self.silent or name not in self.registers:
            return
        if action == "set":
            if not self.ignore_writes:
                self.registers[name] = payload
            value = payload  # the echo shows what was sent, applied or not
        else:
            value = self.registers[name]
        self.hass.loop.call_soon(
            async_fire_mqtt_message,
            self.hass,
            base,
            f'{{"value": {{"value": "{value}"}}}}',
        )

    def writes(self) -> list[tuple[str, str]]:
        return [s for s in self.sent if s[0].endswith("/set")]


@pytest.fixture
async def ebusd(hass, mqtt_mock):
    fake = FakeEbusd(hass)
    with (
        patch("homeassistant.components.mqtt.async_publish", fake.publish),
        patch.object(boiler, "SETTLE_SECONDS", 0),
        patch.object(boiler, "READ_TIMEOUT", 0.2),
    ):
        yield fake
