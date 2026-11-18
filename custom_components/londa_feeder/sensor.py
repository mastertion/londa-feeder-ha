"""备用电池电量传感器."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import LondaFeederCoordinator
from .entity import LondaEntity

_LOGGER = logging.getLogger(__name__)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LondaFeederCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if coordinator.battery_dp:
        entities.append(LondaBatterySensor(coordinator, entry))
    async_add_entities(entities)


class LondaBatterySensor(LondaEntity, SensorEntity):
    """备用电池剩余电量（%）。"""

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery"

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_battery"

    @property
    def native_value(self) -> float | None:
        return _as_number(self.coordinator.dp_value(self.coordinator.battery_dp))
