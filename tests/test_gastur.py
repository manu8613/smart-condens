"""Prices and meter taken from the Gas TUR integration."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
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
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.smart_condens import const as c
from custom_components.smart_condens import detect, gastur
from custom_components.smart_condens.dashboard import panel_path
from custom_components.smart_condens.manager import statistic_id

from .conftest import make_entry, set_house

METER = "sensor.my_meter"
PRICE = "sensor.my_energy_price"


def attributes(history: list[tuple[date, float, float]]) -> dict:
    """What the energy price sensor of Gas TUR publishes (made-up prices)."""
    return {
        "impuesto_hidrocarburos": 0.002,
        "iva": 21.0,
        "alquiler_contador_dia": 0.02,
        "factor_conversion": 10.0,
        "historial": [
            {"start": day.isoformat(), "fixed_month": fixed, "variable": variable}
            for day, fixed, variable in reversed(history)
        ],
    }


def add_gas_tur(hass, attrs: dict | None) -> None:
    source = MockConfigEntry(domain=gastur.DOMAIN)
    source.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, entity_id in (
        (gastur.METER, METER),
        (gastur.PRICE, PRICE),
        ("coste_hoy", "sensor.my_cost_today"),
    ):
        registry.async_get_or_create(
            "sensor",
            gastur.DOMAIN,
            f"{source.entry_id}_{key}",
            suggested_object_id=entity_id.split(".")[1],
            config_entry=source,
        )
    hass.states.async_set(METER, "500", {"unit_of_measurement": "m³"})
    hass.states.async_set("sensor.my_cost_today", "1.5")
    if attrs is None:
        hass.states.async_set(PRICE, "unavailable")
    else:
        hass.states.async_set(PRICE, "0.05", attrs)


def test_tariff_adds_taxes_like_the_bill():
    tariff = gastur.tariff(
        attributes([(date(2026, 7, 1), 9.0, 0.05), (date(2026, 10, 1), 10.0, 0.06)])
    )
    price, fixed = tariff.on(date(2026, 11, 1))
    assert price == pytest.approx((0.06 + 0.002) * 1.21, abs=1e-6)
    assert fixed == pytest.approx((10 * 12 / 365 + 0.02) * 1.21, abs=1e-5)
    assert tariff.on(date(2026, 8, 1))[0] < price
    # Days before the first known price use it.
    assert tariff.on(date(2025, 1, 1)) == tariff.on(date(2026, 7, 1))


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {**attributes([]), "iva": None},
        attributes([]),
        attributes([(date(2026, 1, 1), 9.0, 50.0)]),
    ],
)
def test_odd_prices_give_no_tariff(broken):
    assert gastur.tariff(broken).on(date(2026, 11, 1)) is None


async def test_wizard_proposes_the_gas_tur_meter(hass):
    add_gas_tur(hass, None)
    hass.states.async_set(
        "sensor.other_gas",
        "1",
        {"device_class": "energy", "state_class": "total_increasing"},
    )
    assert detect.house_suggestions(hass)[c.CONF_GAS] == METER


async def _gas_history(hass, changed: date) -> None:
    today = dt_util.now().date()
    for statistic, unit, unit_class, has_sum in (
        (METER, "m³", "volume", True),
        ("sensor.outdoor", "°C", "temperature", False),
    ):
        points, total = [], 0.0
        for back in range(20, 0, -1):
            day = today - timedelta(days=back)
            start = dt_util.as_utc(dt_util.start_of_local_day(day))
            if has_sum:
                total += 4.0 if day < changed else 3.6
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


async def _setup(hass, attrs: dict | None, **changes):
    changed = dt_util.now().date() - timedelta(days=6)
    await _gas_history(hass, changed)
    assert await async_setup_component(hass, "lovelace", {})
    set_house(hass)
    add_gas_tur(hass, attrs)
    entry = make_entry(
        **{c.CONF_GAS: METER, c.CONF_CHANGE_DATE: changed.isoformat(), **changes}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    await manager.async_update_gas()
    await async_wait_recording_done(hass)
    return entry, manager, changed


async def test_meter_in_m3_and_regulated_prices(hass):
    today = dt_util.now().date()
    history = [(today - timedelta(days=90), 10.0, 0.05)]
    entry, manager, _ = await _setup(hass, attributes(history))
    price, fixed = gastur.tariff(attributes(history)).on(today)
    assert (manager.gas["before"], manager.gas["after"]) == (4.0, 3.6)  # kWh/GD
    assert manager.gas["price_source"] == "gas_tur"
    assert manager.gas["kwh_per_m3"] == 10.0
    # Five valid days after, 4 kWh less each; the fixed term is not a saving.
    assert manager.gas["saved_eur"] == pytest.approx(5 * 4 * price, abs=0.01)
    assert manager.gas["rows"][-1]["cost"] == pytest.approx(36 * price + fixed)

    series = statistic_id(entry, "cost")
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
    assert stats[series][-1]["change"] == pytest.approx(36 * price + fixed, abs=0.001)

    panel = await hass.async_add_executor_job(load_yaml_dict, str(panel_path(hass)))
    gas = str(panel["views"][2])
    assert "sensor.my_cost_today" in gas
    assert "Gas total (m³)" in gas

    # A new price recalculates on its own.
    hass.states.async_set(
        PRICE, "0.1", attributes([(today - timedelta(days=90), 10.0, 0.1)])
    )
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    await hass.async_block_till_done()
    assert manager.gas["price_kwh"] > price


async def test_unavailable_prices_are_not_replaced(hass):
    _, manager, _ = await _setup(hass, None)
    assert manager.gas == {
        "price_source": "gas_tur_sin_datos",
        "problem": "factor",
        "rows": [],
    }


async def test_manual_price_when_chosen(hass):
    today = dt_util.now().date()
    _, manager, _ = await _setup(
        hass,
        attributes([(today - timedelta(days=90), 10.0, 0.05)]),
        **{c.CONF_GAS_TUR: False},
    )
    assert manager.gas["price_source"] == "manual"
    assert manager.gas["price_kwh"] == 0.07
    assert manager.gas["saved_eur"] == pytest.approx(5 * 4 * 0.07)
    panel = await hass.async_add_executor_job(load_yaml_dict, str(panel_path(hass)))
    assert "sensor.my_cost_today" not in str(panel)
