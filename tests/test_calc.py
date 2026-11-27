"""The calculations."""

from datetime import date, timedelta

from custom_components.smart_condens import calc


def _run(state, temps, demand, target=21.0, outdoor=5.0, start=0):
    for i, temp in enumerate(temps, start):
        assert calc.sample_room(state, i * 3600.0, temp, target, demand, outdoor)


def test_cooling_gives_inertia():
    state = calc.RoomState()
    _run(state, [20 - 0.2 * i for i in range(8)], demand=0)
    assert state.cooling == 0.2
    assert state.cool_samples == 7
    assert calc.inertia_label(state) == "Buena"


def test_unmet_room_asks_to_raise():
    state = calc.RoomState()
    _run(state, [18.0, 18.1, 18.2], demand=50)
    assert state.heating == 0.1
    assert state.unmet_run == 3
    assert calc.room_advice(state, 18.2, 21, 50, 20) == "Subir: no llega"


def test_early_sample_and_gap():
    state = calc.RoomState()
    assert calc.sample_room(state, 0, 18, 21, 50, 5)
    assert not calc.sample_room(state, 600, 18, 21, 50, 5)
    assert not calc.sample_room(state, 3600, None, 21, 50, 5)
    assert calc.sample_room(state, 36000, 18, 21, 50, 5)
    assert state.rate is None
    assert state.unmet_run == 1
    assert calc.RoomState.from_dict(state.as_dict()) == state


def test_valve_offset_advice():
    state = calc.RoomState()
    assert calc.room_advice(state, 19, 21, 0, 21.5) == "Corregir desfase de la válvula"
    assert calc.room_advice(state, 22, 21, 0, 22) == "Sobra calor"
    assert calc.room_advice(state, None, 21, 0, 22) == "Sin datos"


def test_valve_states():
    assert calc.valve_state(19, 21, 0, True, 0, None) == "Cerrada y falta calor"
    assert calc.valve_state(21, 21, 0, True, 0, None) == "Cerrada"
    assert calc.valve_state(19, 21, 50, False, 0, None) == "Pide, circuito frío"
    assert calc.valve_state(19, 21, 50, True, 10, None) == "Abierta, esperando"
    assert calc.valve_state(19, 21, 50, True, 90, -0.1) == "Abierta y no sube"
    assert calc.valve_state(19, 21, 50, True, 90, 0.3) == "Abierta"


def test_radiator_watts_fall_along_the_loop():
    first = calc.radiator_watts(8, 120, 1, 5, 60, 50, 20, 50, True)
    last = calc.radiator_watts(8, 120, 5, 5, 60, 50, 20, 50, True)
    assert first > last > 0
    assert calc.radiator_watts(8, 120, 1, 5, 60, 50, 20, 0, True) == 0
    assert calc.radiator_watts(0, 120, 1, 5, 60, 50, 20, 50, True) is None


def test_recommendation():
    ok = {"A": calc.RoomState(history=[0] * 24)}
    bad = {"A": calc.RoomState(history=[1] * 24, unmet_run=24)}
    assert calc.recommendation({}, 60, 10, None, None)[0] == "Reuniendo datos"
    assert calc.recommendation(ok, 60, 1, 52, 1)[0] == "Mantener 60 °C"
    assert calc.recommendation(ok, 60, 10, 52, 1)[0] == "Bajar a 57 °C"
    assert calc.recommendation(bad, 60, 10, 52, 1)[0] == "Subir a 63 °C"
    assert calc.recommendation(bad, 65, 10, 52, 5)[0] == "No subir más: revisar"


def test_gas_summary():
    change = date(2026, 11, 10)
    days = [(change - timedelta(days=i), 50.0, 8.0) for i in range(1, 6)]
    days += [(change + timedelta(days=i), 45.0, 8.0) for i in range(6)]
    result = calc.gas_summary(days, change, 18, 5, 0.1, change + timedelta(days=10))
    assert (result["before"], result["after"]) == (4.5, 4.0)
    assert result["days_after"] == 5  # the change day is left out
    assert result["saving_pct"] == 11.1
    assert result["saved_eur"] == 2.5
    assert round(result["rows"][-1]["diff"], 2) == -0.5


def test_summer_baseline():
    assert calc.dhw_baseline([3.0] * 20, 0) == (3.0, True)
    assert calc.dhw_baseline([3.0], 0) == (0.0, False)
    assert calc.previous_summer(date(2026, 11, 1))[0] == date(2026, 7, 1)
    assert calc.previous_summer(date(2026, 3, 1))[0] == date(2025, 7, 1)
