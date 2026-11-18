"""缺粮 / 卡粮告警."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import LondaFeederCoordinator
from .entity import LondaEntity

_TRUTHY = {"true", "1", "on", "yes", "empty", "lack", "no_food", "nofood",
           "jam", "block", "blocked", "error", "alarm", "缺粮", "卡粮", "告警"}


def _is_problem(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LondaFeederCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if coordinator.feeding_dp:
        entities.append(LondaFeedingSensor(coordinator, entry))
    if coordinator.no_food_dp:
        entities.append(LondaNoFoodSensor(coordinator, entry))
    if coordinator.jam_dp:
        entities.append(LondaJamSensor(coordinator, entry))
    async_add_entities(entities)


class LondaFeedingSensor(LondaEntity, BinarySensorEntity):
    """设备正在出粮（投喂中）。"""

    _attr_translation_key = "feeding"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:fish"

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_feeding"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.dp_value(self.coordinator.feeding_dp)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "on", "yes")
        return None


class _LondaProblemSensor(LondaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    dp_attr: str = ""

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry, suffix: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{suffix}"

    @property
    def is_on(self) -> bool | None:
        return _is_problem(
            self.coordinator.dp_value(getattr(self.coordinator, self.dp_attr))
        )


class LondaNoFoodSensor(_LondaProblemSensor):
    """食槽缺粮。"""

    _attr_translation_key = "no_food"
    _attr_icon = "mdi:food-off"
    dp_attr = "no_food_dp"

    def __init__(self, coordinator: LondaFeederCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "no_food")


class LondaJamSensor(_LondaProblemSensor):
    """出粮卡粮。"""

    _attr_translation_key = "jam"
    _attr_icon = "mdi:alert"
    dp_attr = "jam_dp"

    def __init__(self, coordinator: LondaFeederCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "jam")
