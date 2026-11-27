"""Smart Condens: heating analysis per room, gas before/after and boiler settings."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .const import CONF_DASHBOARD, DOMAIN, STORAGE_VERSION
from .dashboard import async_remove_dashboard, async_setup_dashboard
from .manager import Manager, SmartCondensConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartCondensConfigEntry
) -> bool:
    manager = Manager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    async def _started(_hass: HomeAssistant) -> None:
        manager.async_track_demand()
        manager.async_sample()
        manager.async_notify()
        await manager.async_update_gas()

    entry.async_on_unload(async_at_started(hass, _started))

    if manager.cfg.get(CONF_DASHBOARD, True):
        await async_setup_dashboard(hass, entry)
    return True


async def _async_reload(hass: HomeAssistant, entry: SmartCondensConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: SmartCondensConfigEntry
) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.boiler.async_shutdown()
        await entry.runtime_data.async_save()
        async_remove_dashboard(hass, entry)
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: SmartCondensConfigEntry
) -> None:
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
