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
    if coordinator.feed_dp:
        entities.append(LondaLastFeedSensor(coordinator, entry))
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


class LondaLastFeedSensor(LondaEntity, SensorEntity):
    """最近一次投喂的份数（设备上报 DP 归零前抓到的出粮份数）。"""

    _attr_translation_key = "last_feed"
    _attr_icon = "mdi:fish"
    _attr_native_unit_of_measurement = "份"
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_last_feed_portions"

    @property
    def native_value(self) -> int | None:
        portions = self.coordinator.last_feed_portions
        return None if portions is None else int(portions)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last_at = self.coordinator.last_feed_at
        return {
            "last_feed_at": last_at.isoformat() if last_at else None,
            "portions_per_feed": self.coordinator.portions,
            "feed_count": self.coordinator.feed_count,
        }
