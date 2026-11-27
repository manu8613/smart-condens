"""Pure calculations: no Home Assistant imports, so they are easy to test."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

HISTORY = 24
MIN_COOL_SAMPLES = 6

NO_DATA = "Sin datos"


@dataclass
class RoomState:
    """Everything a room remembers between hourly samples."""

    last_temp: float | None = None
    last_ts: float | None = None
    last_demand: float | None = None
    rate: float | None = None
    heating: float | None = None
    cooling: float | None = None
    inertia: float | None = None
    cool_samples: int = 0
    history: list[int] = field(default_factory=list)
    unmet_run: int = 0
    open_since: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RoomState:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ema(old: float | None, new: float) -> float:
    return round(new if old is None else 0.8 * old + 0.2 * new, 2)


def sample_room(
    state: RoomState,
    ts: float,
    temp: float | None,
    target: float | None,
    demand: float | None,
    outdoor: float | None,
) -> bool:
    """Take the hourly sample. Returns False if it was too early or had no data."""
    if temp is None or demand is None:
        return False
    hours = None if state.last_ts is None else (ts - state.last_ts) / 3600
    if hours is not None and hours < 0.75:
        return False
    if hours is not None and hours <= 1.5 and state.last_temp is not None:
        rate = (temp - state.last_temp) / hours
        state.rate = round(rate, 2)
        before = state.last_demand or 0
        if demand > 0 and before > 0:
            state.heating = _ema(state.heating, rate)
        elif demand == 0 and before == 0 and rate < 0:
            state.cooling = _ema(state.cooling, -rate)
            if outdoor is not None and temp - outdoor > 3 and -rate >= 0.05:
                state.inertia = round(_ema(state.inertia, (temp - outdoor) / -rate), 1)
                state.cool_samples += 1
    else:
        state.rate = None
        state.unmet_run = 0
    unmet = int(demand > 0 and target is not None and target - temp >= 0.5)
    state.unmet_run = state.unmet_run + 1 if unmet else 0
    state.history = (state.history + [unmet])[-HISTORY:]
    state.last_temp, state.last_ts, state.last_demand = temp, ts, demand
    return True


def circulating(flow: float | None, temp: float | None, dhw: bool) -> bool:
    return not dhw and flow is not None and temp is not None and flow >= temp + 5


def valve_state(
    temp: float | None,
    target: float | None,
    demand: float | None,
    circuit_hot: bool,
    minutes_open: float,
    rate: float | None,
) -> str:
    if temp is None or demand is None:
        return NO_DATA
    short = 0.0 if target is None else target - temp
    if demand <= 0:
        return "Cerrada y falta calor" if short >= 0.5 else "Cerrada"
    if not circuit_hot:
        return "Pide, circuito frío"
    if minutes_open < 60:
        return "Abierta, esperando"
    if rate is not None and rate <= 0 and short >= 0.3:
        return "Abierta y no sube"
    return "Abierta"


def radiator_watts(
    elements: float,
    watts_element: float,
    order: int,
    loop_size: int,
    flow: float | None,
    ret: float | None,
    temp: float | None,
    demand: float | None,
    circuit_hot: bool,
) -> int | None:
    """Rough estimate for a radiator on a one-pipe loop (rated at deltaT 50)."""
    if elements <= 0 or temp is None or demand is None:
        return None
    if demand <= 0 or not circuit_hot:
        return 0
    if flow is None or ret is None:
        return None
    if order > 0 and loop_size > 0:
        mean = flow - (flow - ret) * ((min(order, loop_size) - 0.5) / loop_size)
    else:
        mean = (flow + ret) / 2
    return round(elements * watts_element * (max(mean - temp, 0) / 50) ** 1.3)


def room_advice(
    state: RoomState,
    temp: float | None,
    target: float | None,
    demand: float | None,
    valve_temp: float | None,
) -> str:
    if temp is None or demand is None:
        return NO_DATA
    if state.unmet_run >= 3:
        return "Subir: no llega"
    if target is not None and target > 5:
        if temp - target >= 0.7:
            return "Sobra calor"
        if (
            demand <= 0
            and target - temp >= 0.5
            and valve_temp is not None
            and valve_temp - temp >= 1
        ):
            return "Corregir desfase de la válvula"
    return "Vigilar" if state.unmet_run else "Bien"


def inertia_label(state: RoomState) -> str:
    if state.inertia is None or state.cool_samples < MIN_COOL_SAMPLES:
        return "Midiendo"
    if state.inertia >= 40:
        return "Buena"
    return "Media" if state.inertia >= 20 else "Baja"


def recommendation(
    rooms: dict[str, RoomState],
    flow_set: float,
    days_since_change: int | None,
    return_avg: float | None,
    starts: float | None,
) -> tuple[str, str]:
    """Whether to raise, keep or lower the flow temperature, and why."""
    flow = round(flow_set)
    keep = f"Mantener {flow} °C"
    failing = [
        name for name, s in rooms.items() if sum(s.history) >= 4 or s.unmet_run >= 3
    ]
    if not any(len(s.history) >= 12 for s in rooms.values()):
        what, why = "Reuniendo datos", "Hacen falta 12 horas de muestras"
    elif days_since_change is not None and 0 <= days_since_change < 3:
        what, why = keep, f"En prueba, día {days_since_change} de 3"
    elif failing and flow < 65:
        what = f"Subir a {min(flow + 3, 65)} °C"
        why = "No llegan: " + ", ".join(failing)
    elif failing:
        what = "No subir más: revisar"
        why = f"Con {flow} °C no llegan: " + ", ".join(failing)
    elif (
        not any(sum(s.history) for s in rooms.values())
        and flow > 50
        and return_avg is not None
        and return_avg > 50
    ):
        what = f"Bajar a {max(flow - 3, 50)} °C"
        why = f"Todas llegan y el retorno medio es {return_avg:.1f} °C"
    else:
        what, why = keep, "Sin motivo para cambiar"
    if starts is not None and starts > 3:
        why += f". Ojo: {starts:.0f} arranques en la última hora"
    return what, why


def dhw_baseline(summer_days: list[float], manual: float) -> tuple[float, bool]:
    """kWh/day used for hot water, and whether the figure is trustworthy."""
    if manual > 0:
        return manual, True
    if len(summer_days) >= 15:
        return sum(summer_days) / len(summer_days), True
    return 0.0, False


@dataclass(frozen=True)
class Tariff:
    """From each date on: price of a kWh and fixed cost of a day, with taxes."""

    periods: tuple[tuple[date, float, float], ...] = ()

    @classmethod
    def flat(cls, price: float) -> Tariff:
        return cls(((date.min, price, 0.0),)) if price > 0 else cls()

    def on(self, day: date) -> tuple[float, float] | None:
        """The earliest known prices are used for the days before them."""
        if not self.periods:
            return None
        current = self.periods[0]
        for period in self.periods:
            if period[0] <= day:
                current = period
        return current[1], current[2]


def gas_summary(
    days: list[tuple[date, float, float]],
    change: date,
    base: float,
    dhw: float,
    price: float | Tariff,
    today: date,
) -> dict[str, Any]:
    """Compare heating gas per degree-day before and after the change.

    days: (day, gas kWh, mean outdoor temperature). The change day is left out.
    """
    totals = {"before": [0.0, 0.0, 0], "after": [0.0, 0.0, 0]}
    rows: list[dict[str, Any]] = []
    for day, gas, outdoor in sorted(days):
        if day == change or day >= today:
            continue
        degree = max(base - outdoor, 0.0)
        heat = max(gas - dhw, 0.0)
        period = "before" if day < change else "after"
        if degree >= 3:
            totals[period][0] += heat
            totals[period][1] += degree
            totals[period][2] += 1
        rows.append(
            {
                "date": day,
                "period": period,
                "gas": gas,
                "heat": heat,
                "outdoor": outdoor,
                "degree": degree,
                "ratio": heat / degree if degree >= 3 else None,
            }
        )
    before, after = totals["before"], totals["after"]
    r_before = before[0] / before[1] if before[2] >= 3 else None
    r_after = after[0] / after[1] if after[2] >= 3 else None
    tariff = price if isinstance(price, Tariff) else Tariff.flat(price)
    saving = None
    saved_eur = None
    if r_before and r_after is not None:
        saving = round((1 - r_after / r_before) * 100, 1)
    for row in rows:
        prices = tariff.on(row["date"])
        row["cost"] = None if prices is None else row["gas"] * prices[0] + prices[1]
        # Only the energy changes with the boiler: the fixed term is paid anyway.
        row["diff"] = (
            (row["heat"] - r_before * row["degree"]) * prices[0]
            if prices is not None
            and r_before
            and row["period"] == "after"
            and row["ratio"] is not None
            else None
        )
    if saving is not None and tariff.periods:
        saved = [row["diff"] for row in rows if row["diff"] is not None]
        saved_eur = round(0.0 - sum(saved), 2)
    return {
        "before": None if r_before is None else round(r_before, 2),
        "after": None if r_after is None else round(r_after, 2),
        "days_before": before[2],
        "days_after": after[2],
        "saving_pct": saving,
        "saved_eur": saved_eur,
        "rows": rows,
    }


def previous_summer(today: date) -> tuple[date, date]:
    """First and one-past-last day of the latest complete July-August."""
    year = today.year if today.month >= 9 else today.year - 1
    return date(year, 7, 1), date(year, 8, 31) + timedelta(days=1)
