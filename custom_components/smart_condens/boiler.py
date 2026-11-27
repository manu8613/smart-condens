"""Boiler settings over ebusd (MQTT). Nothing is ever written without confirmation.

Flow of a change: prepare (reads the boiler) -> the user sees old and new value ->
confirm (re-reads, writes once, reads back). Automations cannot confirm.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

PENDING_SECONDS = 120
MIN_SECONDS_BETWEEN_WRITES = 60
READ_TIMEOUT = 10
SUBSCRIBE_TIMEOUT = 10
SETTLE_SECONDS = 3


@dataclass(frozen=True)
class Param:
    key: str
    message: str
    label: str
    unit: str
    touches: str
    minimum: float = 0
    maximum: float = 0
    read_range: tuple[float, float] = (0, 0)
    options: tuple[str, ...] = ()


PARAMS: dict[str, Param] = {
    "flow_max": Param(
        key="flow_max",
        message="FlowsetHcMax",
        label="Tope de temperatura de ida (d.71)",
        unit="°C",
        minimum=45,
        maximum=70,
        read_range=(30, 90),
        touches=(
            "El ajuste de instalador d.71 de la caldera: el máximo de ida en "
            "calefacción. Es un tope, así que el termostato puede pedir menos. "
            "Subirlo puede no subir la ida si el mando de la caldera está más bajo. "
            "No cambia el agua caliente."
        ),
    ),
    "pump": Param(
        key="pump",
        message="PumpPowerDesired",
        label="Potencia de la bomba (d.14)",
        unit="%",
        options=("auto", "53", "60", "70", "85", "100"),
        touches=(
            "El ajuste de instalador d.14: la velocidad de la bomba de calefacción. "
            "En monotubo, menos caudal deja más fríos los últimos radiadores del "
            "anillo; más caudal puede hacer ruido y sube el retorno."
        ),
    ),
}


def parse_payload(payload: str) -> str | None:
    """Value inside an ebusd MQTT payload, plain or JSON."""
    text = payload.strip()
    if not text:
        return None
    try:
        data: Any = json.loads(text)
    except ValueError:
        data = text
    while isinstance(data, dict):
        if "value" in data:
            data = data["value"]
        elif "fields" in data:
            data = data["fields"]
        elif len(data) == 1:
            data = next(iter(data.values()))
        else:
            return None
    if data is None or isinstance(data, (bool, list)):
        return None
    return normalize(str(data))


def normalize(value: str) -> str | None:
    text = value.strip().lstrip("_").lower()
    if text in ("", "-", "null"):
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else str(number)


def plausible(param: Param, value: str) -> bool:
    """Guard against a wrong ebusd profile decoding some other register."""
    if param.options:
        return value in param.options
    try:
        number = float(value)
    except ValueError:
        return False
    low, high = param.read_range
    return low <= number <= high


@dataclass
class Pending:
    param: Param
    old: str
    new: str
    expires: float


class Boiler:
    """Reads and, only after confirmation, writes two boiler settings."""

    def __init__(
        self,
        hass: HomeAssistant,
        topic: str,
        circuit: str,
        allow_write: bool,
        notify: Callable[[], None],
    ) -> None:
        self.hass = hass
        self.base = f"{topic.strip('/')}/{circuit}"
        self.allow_write = allow_write
        self._notify = notify
        self.values: dict[str, str | None] = dict.fromkeys(PARAMS)
        self.proposed: dict[str, str | None] = dict.fromkeys(PARAMS)
        self.pending: Pending | None = None
        self.status = "Sin leer"
        self.log: list[str] = []
        self._lock = asyncio.Lock()
        self._last_write = 0.0
        self._cancel_expiry: Callable[[], None] | None = None

    async def _async_request(
        self, param: Param, action: str, payload: str
    ) -> str | None:
        """Publish topic/get or topic/set and wait for ebusd to answer on topic."""
        from homeassistant.components import mqtt

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise HomeAssistantError("MQTT no está disponible en Home Assistant")
        topic = f"{self.base}/{param.message}"
        answer: asyncio.Future[str] = self.hass.loop.create_future()

        @callback
        def _received(msg: Any) -> None:
            # A retained message is an old value: only a fresh answer counts.
            if msg.retain or answer.done():
                return
            if (value := parse_payload(str(msg.payload))) is not None:
                answer.set_result(value)

        subscribed = asyncio.Event()
        unsubscribe = await mqtt.async_subscribe(self.hass, topic, _received)
        # Home Assistant batches subscriptions: asking before ours reaches the
        # broker would lose the answer.
        stop_waiting = mqtt.async_on_subscribe_done(self.hass, topic, 0, subscribed.set)
        try:
            async with asyncio.timeout(SUBSCRIBE_TIMEOUT):
                await subscribed.wait()
            await mqtt.async_publish(self.hass, f"{topic}/{action}", payload)
            async with asyncio.timeout(READ_TIMEOUT):
                return await answer
        except TimeoutError:
            return None
        finally:
            stop_waiting()
            unsubscribe()

    async def _async_read(self, param: Param) -> str | None:
        """Ask ebusd to read the register from the boiler right now."""
        return await self._async_request(param, "get", "")

    async def async_refresh(self) -> None:
        async with self._lock:
            for key, param in PARAMS.items():
                value = await self._async_read(param)
                if value is not None and not plausible(param, value):
                    value = None
                self.values[key] = value
                if self.proposed[key] is None:
                    self.proposed[key] = value
            ok = [PARAMS[k].label for k, v in self.values.items() if v is not None]
            self.status = (
                "Leído: " + ", ".join(ok)
                if ok
                else "La caldera no responde a estos ajustes por ebusd"
            )
        self._notify()

    async def async_prepare(self, key: str) -> None:
        param = PARAMS[key]
        if not self.allow_write:
            raise HomeAssistantError(
                "La escritura en la caldera está desactivada en las opciones"
            )
        new = normalize(self.proposed.get(key) or "")
        if new is None:
            raise HomeAssistantError("Elige primero el valor nuevo")
        if param.options:
            if new not in param.options:
                raise HomeAssistantError(f"Valor no permitido: {new}")
        elif (
            not (param.minimum <= float(new) <= param.maximum)
            or not float(new).is_integer()
        ):
            raise HomeAssistantError(
                f"Solo se admite de {param.minimum:g} a {param.maximum:g} {param.unit}"
            )
        async with self._lock:
            self._clear_pending()
            old = await self._async_read(param)
            self.values[key] = old if old and plausible(param, old) else None
            if self.values[key] is None:
                self.status = f"No se puede leer «{param.label}»: no se prepara nada"
                self._notify()
                raise HomeAssistantError(self.status)
            if old == new:
                self.status = f"«{param.label}» ya está en {new}"
                self._notify()
                raise HomeAssistantError(self.status)
            self.pending = Pending(param, old, new, time.monotonic() + PENDING_SECONDS)
            self._cancel_expiry = async_call_later(
                self.hass, PENDING_SECONDS, self._expired
            )
            self.status = "Cambio preparado, sin enviar"
        self._notify()

    @property
    def warning(self) -> str:
        if (p := self.pending) is None:
            return ""
        unit = "" if p.new == "auto" else f" {p.param.unit}"
        old_unit = "" if p.old == "auto" else f" {p.param.unit}"
        return (
            f"Vas a cambiar **{p.param.label}** de **{p.old}{old_unit}** a "
            f"**{p.new}{unit}**.\n\nQué se toca: {p.param.touches}\n\n"
            f"Mensaje ebusd: `{p.param.message}`. Caduca a los "
            f"{PENDING_SECONDS // 60} minutos."
        )

    async def async_confirm(self) -> None:
        async with self._lock:
            pending = self.pending
            if pending is None or time.monotonic() > pending.expires:
                self._clear_pending()
                self._notify()
                raise HomeAssistantError("No hay ningún cambio pendiente o ha caducado")
            if not self.allow_write:
                raise HomeAssistantError("La escritura en la caldera está desactivada")
            wait = self._last_write + MIN_SECONDS_BETWEEN_WRITES - time.monotonic()
            if self._last_write and wait > 0:
                raise HomeAssistantError(
                    f"Espera {wait:.0f} s antes de otro cambio en la caldera"
                )
            self._clear_pending()
            param = pending.param
            current = await self._async_read(param)
            if current != pending.old:
                self._finish(
                    f"No enviado: «{param.label}» ya no vale {pending.old} "
                    f"(ahora: {current or 'sin respuesta'})"
                )
                return
            self._last_write = time.monotonic()
            # ebusd echoes what it wrote. That is not proof: consume the echo,
            # let it settle and then ask the boiler again.
            await self._async_request(param, "set", pending.new)
            await asyncio.sleep(SETTLE_SECONDS)
            result = await self._async_read(param)
            if result is None:
                await asyncio.sleep(SETTLE_SECONDS)
                result = await self._async_read(param)
            self.values[param.key] = result
            if result == pending.new:
                text = f"Aplicado y comprobado: {param.label} {pending.old} → {result}"
            elif result is None:
                text = (
                    f"Enviado pero SIN comprobar: mira {param.label} en la caldera "
                    f"(antes: {pending.old}, pedido: {pending.new})"
                )
            else:
                text = (
                    f"NO aplicado: {param.label} sigue en {result}. Revisa que ebusd "
                    "tenga nivel de acceso «install»; la caldera también puede ignorarlo"
                )
            self._finish(text)

    @callback
    def async_cancel(self) -> None:
        had = self.pending is not None
        self._clear_pending()
        if had:
            self.status = "Cambio cancelado, no se ha enviado nada"
        self._notify()

    def _finish(self, text: str) -> None:
        self.status = text
        stamp = time.strftime("%d/%m %H:%M")
        self.log = ([f"{stamp} · {text}"] + self.log)[:10]
        _LOGGER.warning("Ajuste de caldera: %s", text)
        self._notify()

    @callback
    def _expired(self, _now: Any) -> None:
        self._cancel_expiry = None
        if self.pending is not None:
            self.pending = None
            self.status = "El cambio preparado ha caducado, no se ha enviado nada"
            self._notify()

    def _clear_pending(self) -> None:
        self.pending = None
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None

    @callback
    def async_shutdown(self) -> None:
        self._clear_pending()
