"""Build the dashboard (native Home Assistant cards only)."""

from __future__ import annotations

from typing import Any

HOUSE_KEYS = {
    "recommendation": "sensor",
    "return_average": "sensor",
    "delta": "sensor",
    "gas_saving": "sensor",
    "boiler_flow_max": "sensor",
    "boiler_pump": "sensor",
    "boiler_pending": "sensor",
    "boiler_status": "sensor",
    "flow_set": "number",
    "new_flow_max": "number",
    "new_pump": "select",
    "recalculate": "button",
    "read_boiler": "button",
    "prepare_flow_max": "button",
    "prepare_pump": "button",
    "confirm_change": "button",
    "cancel_change": "button",
}
ROOM_KEYS = (
    "advice",
    "temperature",
    "offset",
    "valve",
    "power",
    "heating_rate",
    "cooling_rate",
    "inertia",
)


GAS_TUR_ROWS = (
    ("coste_hoy", "Coste hoy"),
    ("coste_mes", "Coste este mes"),
    ("factura", "Factura hasta hoy"),
    ("prevision_factura", "Previsión de factura"),
)


def _full(card: dict[str, Any]) -> dict[str, Any]:
    card["grid_options"] = {"columns": "full"}
    return card


def _section(title: str, icon: str, cards: list, span: int = 1) -> dict[str, Any]:
    heading = {"type": "heading", "heading": title, "icon": icon}
    return {"type": "grid", "column_span": span, "cards": [heading, *cards]}


def _markdown(content: str) -> dict[str, Any]:
    return _full({"type": "markdown", "content": content})


def _history(title: str, entities: list, hours: int = 24) -> dict[str, Any]:
    return _full(
        {
            "type": "history-graph",
            "title": title,
            "hours_to_show": hours,
            "entities": entities,
        }
    )


def _statistics(title: str, entities: list, stat: str, chart: str = "bar") -> dict:
    return _full(
        {
            "type": "statistics-graph",
            "title": title,
            "entities": entities,
            "stat_types": [stat],
            "period": "day",
            "days_to_show": 30,
            "chart_type": chart,
        }
    )


def _gauge(entity: str, name: str, segments: list) -> dict[str, Any]:
    return {
        "type": "gauge",
        "entity": entity,
        "name": name,
        "min": 20,
        "max": 75,
        "needle": True,
        "segments": segments,
        "grid_options": {"columns": 6},
    }


def _button(entity: str, name: str, icon: str, confirm: str | None = None) -> dict:
    action: dict[str, Any] = {
        "action": "perform-action",
        "perform_action": "button.press",
        "target": {"entity_id": entity},
    }
    if confirm:
        action["confirmation"] = {"text": confirm}
    return {
        "type": "button",
        "entity": entity,
        "name": name,
        "icon": icon,
        "show_state": False,
        "tap_action": action,
        "hold_action": {"action": "none"},
        "grid_options": {"columns": "full", "rows": 2},
    }


def _show(entity: str) -> str:
    """Jinja showing a state, or a dash when there is none."""
    return (
        f"{{{{ states('{entity}') if states('{entity}') not in "
        f"['unknown','unavailable'] else '—' }}}}"
    )


def build_panel(
    house: dict[str, str],
    rooms: list[dict[str, Any]],
    sources: dict[str, str | None],
    series: dict[str, str],
    allow_write: bool,
    gas_tur: dict[str, str] | None = None,
) -> dict[str, Any]:
    """house: our entity ids. rooms: name, climate, sensor and ids.

    sources: the user's flow/return/outdoor/gas entities. series: statistic ids.
    gas_tur: Gas TUR entities by key, empty when its prices are not used.
    """
    flow, ret = sources.get("flow"), sources.get("return")
    outdoor, gas = sources.get("outdoor"), sources.get("gas")

    now = ""  # one short block per room: a wide table does not fit a phone
    waves = "| Estancia | Sube °C/h | Baja °C/h | Inercia |\n|---|---|---|---|\n"
    for room in rooms:
        ids, name = room["ids"], room["name"]
        target = f"{{{{ state_attr('{ids['advice']}','target') or '—' }}}}"
        now += (
            f"**{name}** · {_show(ids['temperature'])} / {target} °C · "
            f"**{_show(ids['advice'])}**\\\n"
            f"{_show(ids['valve'])} · desfase {_show(ids['offset'])} · "
            f"{_show(ids['power'])} W\n\n"
        )
        waves += (
            f"| {name} | {_show(ids['heating_rate'])} "
            f"| {_show(ids['cooling_rate'])} | {_show(ids['inertia'])} |\n"
        )
    if not rooms:
        now = waves = (
            "Añade tus estancias en **Ajustes → Dispositivos y servicios → "
            "Smart Condens → Añadir estancia**."
        )

    reco = house["recommendation"]
    today = [
        _section(
            "Qué hago hoy",
            "mdi:lightbulb-on",
            [
                _markdown(f"## {_show(reco)}\n{{{{ state_attr('{reco}','reason') }}}}"),
                _full(
                    {
                        "type": "tile",
                        "entity": house["flow_set"],
                        "name": "Ida fijada (anotación)",
                    }
                ),
                _button(house["recalculate"], "Recalcular", "mdi:refresh"),
            ],
        ),
        _section(
            "Caldera y calle",
            "mdi:water-boiler",
            [
                _gauge(
                    flow,
                    "Ida",
                    [
                        {"from": 20, "color": "#2196f3"},
                        {"from": 50, "color": "#4caf50"},
                        {"from": 65, "color": "#f44336"},
                    ],
                ),
                _gauge(
                    ret,
                    "Retorno (condensa < 54)",
                    [
                        {"from": 20, "color": "#4caf50"},
                        {"from": 50, "color": "#ff9800"},
                        {"from": 54, "color": "#f44336"},
                    ],
                ),
                _full(
                    {
                        "type": "entities",
                        "entities": [
                            {"entity": outdoor, "name": "Exterior"},
                            {"entity": house["delta"], "name": "Salto ida-retorno"},
                            {
                                "entity": house["return_average"],
                                "name": "Retorno medio 24 h",
                            },
                        ],
                    }
                ),
            ],
        ),
        _section("Estancias ahora", "mdi:radiator", [_markdown(now)], 2),
        _section("Inercia térmica", "mdi:home-thermometer", [_markdown(waves)]),
    ]

    graphs = [
        _section(
            "Circuito",
            "mdi:sine-wave",
            [
                _history(
                    "Ida, retorno y calle · 48 h",
                    [
                        {"entity": flow, "name": "Ida"},
                        {"entity": ret, "name": "Retorno"},
                        {"entity": outdoor, "name": "Exterior"},
                    ],
                    48,
                )
            ],
        )
    ]
    for room in rooms:
        ids = room["ids"]
        lines = [{"entity": ids["temperature"], "name": "Estancia"}]
        if room.get("sensor"):
            lines.append({"entity": room["climate"], "name": "Válvula"})
        graphs.append(
            _section(
                room["name"],
                "mdi:radiator",
                [
                    _history("Temperatura · 24 h", lines),
                    _history(
                        "Radiador (W) y válvula",
                        [
                            {"entity": ids["power"], "name": "W"},
                            {"entity": ids["valve"], "name": "Válvula"},
                        ],
                    ),
                ],
            )
        )

    saving = house["gas_saving"]
    gas_text = (
        f"{{% set e = '{saving}' %}}\n"
        "| | Antes | Después |\n|---|---|---|\n"
        "| kWh por grado-día | {{ state_attr(e,'before') or '—' }} "
        "| {{ state_attr(e,'after') or '—' }} |\n"
        "| Días válidos | {{ state_attr(e,'days_before') or 0 }} "
        "| {{ state_attr(e,'days_after') or 0 }} |\n\n"
        "{% if is_number(states(e)) %}{% set p = states(e) | float %}"
        "**{{ 'Baja' if p > 0 else 'Sube' }} un {{ p | abs }} %**"
        "{% set eur = state_attr(e,'saved_eur') %}{% if eur is not none %} · "
        "{{ 'ahorrados' if eur >= 0 else 'de más' }}: {{ eur | abs }} €{% endif %}"
        "{% if state_attr(e,'days_after') < 14 %}\n\n"
        "_Provisional hasta tener 14 días._{% endif %}"
        "{% else %}Hacen falta el contador de gas, la fecha del cambio y 3 días "
        "válidos en cada periodo.{% endif %}"
        "{% if state_attr(e,'dhw_ok') == false %}\n\n⚠️ Sin datos de verano: pon "
        "el consumo de agua caliente en las opciones.{% endif %}"
        "{% if state_attr(e,'problem') == 'factor' %}\n\n⚠️ El contador está en m³ "
        "y no hay factor de Gas TUR para pasarlo a kWh.{% endif %}"
        "{% set src = state_attr(e,'price_source') %}"
        "{% set kwh = state_attr(e,'price_kwh') %}"
        "{% if src == 'gas_tur' and kwh %}\n\nPrecios de Gas TUR con impuestos: "
        "{{ kwh | round(4) }} €/kWh y "
        "{{ '%.2f' | format(state_attr(e,'fixed_day')) }} "
        "€/día fijo (término fijo y contador)."
        "{% elif src == 'gas_tur_sin_datos' %}\n\n⚠️ Gas TUR no da precios ahora: "
        "no se calculan euros."
        "{% elif src == 'manual' and kwh %}\n\nPrecio manual: {{ kwh }} €/kWh."
        "{% endif %}"
    )
    days_text = (
        "| Día | kWh | Ext. | kWh/GD | ± € |\n|---|---|---|---|---|\n"
        f"{{% for r in (state_attr('{saving}','rows') or []) | reverse %}}"
        "| {{ r.date[8:] }}/{{ r.date[5:7] }} | {{ r.gas }} | {{ r.outdoor }} "
        "| {{ r.ratio or '—' }} "
        "| {% if r.diff is none %}—{% else %}{{ '▲' if r.diff > 0 else '▼' }} "
        "{{ r.diff | abs }}{% endif %} |\n{% endfor %}"
    )
    gas_graphs = [
        _statistics(
            "Coste: ▲ sube / ▼ baja frente a antes (€)", [series["diff"]], "change"
        ),
        _statistics("Coste diario (€)", [series["cost"]], "change"),
        _statistics("Gas de calefacción (kWh)", [series["heat"]], "change"),
    ]
    if outdoor:
        gas_graphs.append(
            _statistics("Temperatura exterior media", [outdoor], "mean", "line")
        )
    if gas:
        unit = sources.get("gas_unit") or "kWh"
        gas_graphs.insert(0, _statistics(f"Gas total ({unit})", [gas], "change"))
    gas_view = [
        _section(
            "Antes y después",
            "mdi:meter-gas",
            [_markdown(gas_text), _markdown(days_text)],
        ),
        _section("Gráficas", "mdi:chart-bar", gas_graphs, 2),
    ]
    costs = [
        {"entity": gas_tur[key], "name": name}
        for key, name in GAS_TUR_ROWS
        if gas_tur and key in gas_tur
    ]
    if costs:
        card = _full({"type": "entities", "entities": costs})
        gas_view.insert(1, _section("Gas TUR", "mdi:cash", [card]))

    pending = house["boiler_pending"]
    boiler_cards: list[dict[str, Any]] = [
        _markdown(
            "⚠️ **Esto cambia ajustes de instalador de tu caldera.** Nada se envía "
            "sin preparar el cambio y confirmarlo. Si no lo tienes claro, no lo "
            "toques."
        ),
        _full(
            {
                "type": "entities",
                "title": "Ahora en la caldera",
                "entities": [
                    {"entity": house["boiler_flow_max"], "name": "Tope ida (°C)"},
                    {"entity": house["boiler_pump"], "name": "Bomba (%)"},
                ],
            }
        ),
        _markdown(f"**{_show(house['boiler_status'])}**"),
        _button(house["read_boiler"], "Leer de la caldera", "mdi:download"),
    ]
    if allow_write:
        boiler = [
            _section("Estado", "mdi:water-boiler", boiler_cards),
            _section(
                "1 · Elegir y preparar",
                "mdi:tune",
                [
                    _full(
                        {
                            "type": "entities",
                            "entities": [
                                {"entity": house["new_flow_max"], "name": "Nuevo tope"}
                            ],
                        }
                    ),
                    _button(
                        house["prepare_flow_max"],
                        "Preparar cambio de ida",
                        "mdi:thermometer-water",
                    ),
                    _full(
                        {
                            "type": "entities",
                            "entities": [
                                {"entity": house["new_pump"], "name": "Bomba"}
                            ],
                        }
                    ),
                    _button(
                        house["prepare_pump"], "Preparar cambio de bomba", "mdi:pump"
                    ),
                ],
            ),
            _section(
                "2 · Revisar y confirmar",
                "mdi:alert",
                [
                    _full(
                        {
                            "type": "conditional",
                            "conditions": [
                                {
                                    "condition": "state",
                                    "entity": pending,
                                    "state": "pending",
                                }
                            ],
                            "card": {
                                "type": "vertical-stack",
                                "cards": [
                                    {
                                        "type": "markdown",
                                        "content": f"{{{{ state_attr('{pending}',"
                                        "'warning') }}",
                                    },
                                    _button(
                                        house["confirm_change"],
                                        "CONFIRMAR y enviar a la caldera",
                                        "mdi:check-bold",
                                        "Se va a escribir en la caldera el cambio "
                                        "que indica el aviso. ¿Seguro?",
                                    ),
                                    _button(
                                        house["cancel_change"],
                                        "Cancelar",
                                        "mdi:close",
                                    ),
                                ],
                            },
                        }
                    ),
                    _markdown(
                        f"{{% for l in state_attr('{house['boiler_status']}',"
                        "'log') or [] %}- {{ l }}\n{% endfor %}"
                    ),
                ],
            ),
        ]
    else:
        boiler_cards.append(
            _markdown(
                "La escritura está **desactivada**. Se activa en las opciones de "
                "Smart Condens y necesita ebusd con nivel de acceso `install` "
                "(léete el README antes)."
            )
        )
        boiler = [_section("Estado", "mdi:water-boiler", boiler_cards)]

    def view(title: str, path: str, icon: str, sections: list) -> dict[str, Any]:
        return {
            "title": title,
            "path": path,
            "icon": icon,
            "type": "sections",
            "max_columns": 3,
            "sections": sections,
        }

    return {
        "views": [
            view("Hoy", "hoy", "mdi:lightbulb-on", today),
            view("Ondas", "ondas", "mdi:chart-bell-curve", graphs),
            view("Gas", "gas", "mdi:meter-gas", gas_view),
            view("Ajustar caldera", "caldera", "mdi:tune-vertical", boiler),
        ]
    }
