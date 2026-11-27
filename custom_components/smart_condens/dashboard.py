"""Create the dashboard in the sidebar when the integration loads.

The dashboard is a YAML-mode Lovelace dashboard generated from the real entity
ids, so it always matches the installed entities. It is rebuilt on every load.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import dump

from .const import (
    CONF_ALLOW_WRITE,
    CONF_CLIMATE,
    CONF_FLOW,
    CONF_GAS,
    CONF_NAME,
    CONF_OUTDOOR,
    CONF_RETURN,
    CONF_TEMP,
    DASHBOARD_URL,
    DOMAIN,
)
from .manager import EXTERNAL_SERIES, SmartCondensConfigEntry, statistic_id
from .panel import HOUSE_KEYS, ROOM_KEYS, build_panel

_LOGGER = logging.getLogger(__name__)

_OURS = f"{DOMAIN}_panels"
TITLE = "Smart Condens"
ICON = "mdi:radiator"


def panel_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN, "panel.yaml"))


def _build(hass: HomeAssistant, entry: SmartCondensConfigEntry) -> dict[str, Any]:
    registry = er.async_get(hass)
    manager = entry.runtime_data

    def lookup(platform: str, owner: str, key: str) -> str:
        found = registry.async_get_entity_id(platform, DOMAIN, f"{owner}_{key}")
        return found or f"{platform}.{DOMAIN}_{key}"

    house = {k: lookup(p, entry.entry_id, k) for k, p in HOUSE_KEYS.items()}
    rooms = [
        {
            "name": room[CONF_NAME],
            "climate": room[CONF_CLIMATE],
            "sensor": room.get(CONF_TEMP),
            "ids": {k: lookup("sensor", sid, k) for k in ROOM_KEYS},
        }
        for sid, room in manager.rooms.items()
    ]
    sources = {
        "flow": manager.cfg.get(CONF_FLOW),
        "return": manager.cfg.get(CONF_RETURN),
        "outdoor": manager.cfg.get(CONF_OUTDOOR),
        "gas": manager.cfg.get(CONF_GAS),
    }
    series = {s: statistic_id(entry, s) for s in EXTERNAL_SERIES}
    return build_panel(
        house, rooms, sources, series, bool(manager.cfg.get(CONF_ALLOW_WRITE))
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dashboards(hass: HomeAssistant) -> dict[str | None, Any] | None:
    data = hass.data.get("lovelace")
    if data is None:
        return None
    return data.dashboards if hasattr(data, "dashboards") else data["dashboards"]


async def async_setup_dashboard(
    hass: HomeAssistant, entry: SmartCondensConfigEntry
) -> None:
    """Write the dashboard YAML and register it in the sidebar."""
    url = DASHBOARD_URL
    path = panel_path(hass)
    await hass.async_add_executor_job(_write, path, dump(_build(hass, entry)))

    ours: set[str] = hass.data.setdefault(_OURS, set())
    dashboards = _dashboards(hass)
    if dashboards is None:
        _LOGGER.warning("Lovelace no está cargado; el panel está en %s", path)
        return
    if url not in ours and (
        url in dashboards or frontend.async_panel_exists(hass, url)
    ):
        _notify(hass, url, path)
        return

    try:
        from homeassistant.components.lovelace.dashboard import LovelaceYAML

        dashboards[url] = LovelaceYAML(
            hass,
            url,
            {
                "mode": "yaml",
                "filename": str(path.relative_to(hass.config.config_dir)),
                "title": TITLE,
                "icon": ICON,
                "show_in_sidebar": True,
                "require_admin": False,
            },
        )
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            sidebar_title=TITLE,
            sidebar_icon=ICON,
            frontend_url_path=url,
            config={"mode": "yaml"},
            require_admin=False,
            update=frontend.async_panel_exists(hass, url),
        )
    except Exception:
        _LOGGER.exception("No se pudo registrar el panel; el YAML está en %s", path)
        _notify(hass, url, path)
        return
    ours.add(url)


@callback
def async_remove_dashboard(hass: HomeAssistant, entry: SmartCondensConfigEntry) -> None:
    """Take the dashboard out of the sidebar (the YAML file stays)."""
    url = DASHBOARD_URL
    ours: set[str] = hass.data.get(_OURS, set())
    if url not in ours:
        return
    ours.discard(url)
    frontend.async_remove_panel(hass, url, warn_if_unknown=False)
    if (dashboards := _dashboards(hass)) is not None:
        dashboards.pop(url, None)


@callback
def _notify(hass: HomeAssistant, url: str, path: Path) -> None:
    persistent_notification.async_create(
        hass,
        (
            f"Ya existe un panel en `/{url}`, así que no lo he sustituido. "
            f"El panel de **{TITLE}** está en `{path}`."
        ),
        title=TITLE,
        notification_id=f"{DOMAIN}_panel",
    )
