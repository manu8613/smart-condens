"""Boiler changes: nothing is sent without a prepared and confirmed change."""

from __future__ import annotations

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.smart_condens import const as c
from custom_components.smart_condens.boiler import (
    PARAMS,
    normalize,
    parse_payload,
    plausible,
)

from .conftest import make_entry
from .test_init import _entity, _setup


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The MQTT test client keeps a periodic timer of its own."""
    return True


def test_payloads():
    assert parse_payload("65.00") == "65"
    assert parse_payload('{"value": {"value": 65}}') == "65"
    assert parse_payload('{"0": {"name": "", "value": "_70"}}') == "70"
    assert parse_payload("auto") == "auto"
    assert parse_payload('{"value": {"value": null}}') is None
    assert parse_payload("") is None
    assert normalize("-") is None
    assert not plausible(PARAMS["flow_max"], "2")
    assert not plausible(PARAMS["pump"], "33")


async def _press(hass, entry, key, user):
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity(hass, entry, "button", key)},
        blocking=True,
        context=Context(user_id=user.id if user else None),
    )


async def _propose(hass, entry, value):
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _entity(hass, entry, "number", "new_flow_max"), "value": value},
        blocking=True,
    )


async def test_change_needs_prepare_and_confirm(hass, ebusd, hass_admin_user):
    entry = make_entry()
    manager = await _setup(hass, entry)
    pending = _entity(hass, entry, "sensor", "boiler_pending")

    with pytest.raises(HomeAssistantError):  # nothing prepared
        await _press(hass, entry, "confirm_change", hass_admin_user)
    await _propose(hass, entry, 60)
    assert ebusd.sent == []  # choosing a value talks to nobody

    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    assert ebusd.writes() == []
    warning = hass.states.get(pending).attributes["warning"]
    assert "**65 °C** a **60 °C**" in warning and "d.71" in warning

    await _press(hass, entry, "confirm_change", hass_admin_user)
    assert ebusd.writes() == [("ebusd/bai/FlowsetHcMax/set", "60")]
    assert manager.boiler.status.startswith("Aplicado y comprobado")
    assert hass.states.get(pending).state == "none"

    with pytest.raises(HomeAssistantError):  # a confirmation is used once
        await _press(hass, entry, "confirm_change", hass_admin_user)
    await _propose(hass, entry, 55)
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    with pytest.raises(HomeAssistantError, match="Espera"):
        await _press(hass, entry, "confirm_change", hass_admin_user)
    assert len(ebusd.writes()) == 1


async def test_echo_is_not_proof(hass, ebusd, hass_admin_user):
    entry = make_entry()
    manager = await _setup(hass, entry)
    ebusd.ignore_writes = True
    await _propose(hass, entry, 60)
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    await _press(hass, entry, "confirm_change", hass_admin_user)
    assert manager.boiler.status.startswith("NO aplicado")


async def test_only_an_administrator_by_hand(
    hass, ebusd, hass_admin_user, hass_read_only_user
):
    entry = make_entry()
    await _setup(hass, entry)
    await _propose(hass, entry, 60)
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    for user in (None, hass_read_only_user):
        with pytest.raises(HomeAssistantError):
            await _press(hass, entry, "confirm_change", user)
    assert ebusd.writes() == []


async def test_aborts(hass, ebusd, hass_admin_user):
    entry = make_entry()
    manager = await _setup(hass, entry)

    ebusd.silent = True
    await _propose(hass, entry, 60)
    with pytest.raises(HomeAssistantError, match="No se puede leer"):
        await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    ebusd.silent = False

    with pytest.raises(HomeAssistantError, match="ya está"):
        await _propose(hass, entry, 65)
        await _press(hass, entry, "prepare_flow_max", hass_admin_user)

    # The boiler changed between prepare and confirm: nothing is sent.
    await _propose(hass, entry, 60)
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    ebusd.registers["FlowsetHcMax"] = "55"
    await _press(hass, entry, "confirm_change", hass_admin_user)
    assert manager.boiler.status.startswith("No enviado")

    # Expired, then cancelled.
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    manager.boiler.pending.expires = 0
    with pytest.raises(HomeAssistantError, match="caducado"):
        await _press(hass, entry, "confirm_change", hass_admin_user)
    await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    await _press(hass, entry, "cancel_change", hass_admin_user)
    assert manager.boiler.pending is None
    assert ebusd.writes() == []


async def test_pump_and_read(hass, ebusd, hass_admin_user):
    entry = make_entry()
    manager = await _setup(hass, entry)
    await _press(hass, entry, "read_boiler", hass_admin_user)
    assert manager.boiler.values == {"flow_max": "65", "pump": "70"}
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _entity(hass, entry, "select", "new_pump"), "option": "auto"},
        blocking=True,
    )
    await _press(hass, entry, "prepare_pump", hass_admin_user)
    await _press(hass, entry, "confirm_change", hass_admin_user)
    assert ebusd.writes() == [("ebusd/bai/PumpPowerDesired/set", "auto")]


async def test_writing_disabled(hass, ebusd, hass_admin_user):
    entry = make_entry(**{c.CONF_ALLOW_WRITE: False})
    await _setup(hass, entry)
    await _propose(hass, entry, 60)
    with pytest.raises(HomeAssistantError, match="desactivada"):
        await _press(hass, entry, "prepare_flow_max", hass_admin_user)
    assert ebusd.sent == []
