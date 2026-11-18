"""Shared entity plumbing for the LONDA feeder."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_DEVICE_ID, CONF_NAME, DEFAULT_NAME, DOMAIN
from .coordinator import LondaFeederCoordinator


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    cfg = {**entry.data, **entry.options}
    return DeviceInfo(
        identifiers={(DOMAIN, cfg[CONF_DEVICE_ID])},
        name=cfg.get(CONF_NAME, DEFAULT_NAME),
        manufacturer="LONDA",
        model="鱼缸自动喂食器",
        configuration_url=f"http://{cfg.get(CONF_ADDRESS)}",
    )


class LondaEntity(CoordinatorEntity[LondaFeederCoordinator]):
    """带设备信息的实体基类。"""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = build_device_info(entry)
