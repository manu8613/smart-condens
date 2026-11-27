"""Prices and meter of the Gas TUR integration, when it is installed.

https://github.com/manu8613/gas-tur. Its entities are found by unique id, so
renaming them changes nothing. The energy price sensor carries the taxes, the
conversion factor and the history of regulated prices as attributes.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .calc import Tariff

DOMAIN = "gas_tur"
METER = "lectura"
PRICE = "precio_kwh"
COSTS = ("coste_hoy", "coste_mes", "factura", "prevision_factura")


@callback
def entities(hass: HomeAssistant, meter: str | None = None) -> dict[str, str]:
    """Entity ids of one gas meter by key: the one owning ``meter`` or the first."""
    found: dict[str, dict[str, str]] = {}
    for entry in er.async_get(hass).entities.values():
        if entry.platform != DOMAIN or entry.disabled_by:
            continue
        for key in (METER, PRICE, *COSTS):
            if entry.unique_id == f"{entry.config_entry_id}_{key}":
                found.setdefault(str(entry.config_entry_id), {})[key] = entry.entity_id
    for owned in found.values():
        if meter in owned.values():
            return owned
    return found[min(found)] if found else {}


def tariff(attributes: Mapping[str, Any]) -> Tariff:
    """Price of a kWh and fixed cost of a day, with taxes, as the bill adds them.

    Taxes and meter rental are the current ones; term and energy prices come
    from the history. Anything missing or odd gives an empty tariff.
    """
    try:
        ieh = float(attributes["impuesto_hidrocarburos"])
        vat = 1 + float(attributes["iva"]) / 100
        rental = float(attributes["alquiler_contador_dia"])
        periods = []
        for period in attributes["historial"]:
            variable = float(period["variable"])
            daily = round(float(period["fixed_month"]) * 12 / 365, 6)
            if not (0 < variable < 1 and 0 <= daily < 5):
                return Tariff()
            periods.append(
                (
                    date.fromisoformat(period["start"]),
                    round((variable + ieh) * vat, 6),
                    round((daily + rental) * vat, 6),
                )
            )
    except (KeyError, TypeError, ValueError):
        return Tariff()
    return Tariff(tuple(sorted(periods)))


def factor(attributes: Mapping[str, Any]) -> float | None:
    """kWh of one cubic metre."""
    try:
        value = float(attributes["factor_conversion"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if 5 < value < 15 else None
