"""每次投喂份数."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    DEFAULT_PORTIONS,
    DOMAIN,
    MAX_PORTIONS,
    MIN_PORTIONS,
)
from .coordinator import LondaFeederCoordinator
from .entity import LondaEntity


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LondaFeederCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.feed_dp:
        async_add_entities([LondaPortionNumber(coordinator, entry)])


class LondaPortionNumber(LondaEntity, NumberEntity):
    """每次投喂份数（1–12 份，仅保存在 HA 侧，按按钮时才下发）。"""

    _attr_translation_key = "portions"
    _attr_icon = "mdi:counter"
    _attr_native_min_value = MIN_PORTIONS
    _attr_native_max_value = MAX_PORTIONS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_portions"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.portions

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_portions(int(value))
