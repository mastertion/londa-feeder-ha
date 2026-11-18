"""手动投喂按钮."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import LondaFeederCoordinator
from .entity import LondaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LondaFeederCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.feed_dp:
        async_add_entities([LondaFeedButton(coordinator, entry)])


class LondaFeedButton(LondaEntity, ButtonEntity):
    """按一次 = 立即投喂一份（份数由设备内保存的计划份数决定）。"""

    _attr_translation_key = "feed_now"
    _attr_icon = "mdi:fish"

    def __init__(
        self, coordinator: LondaFeederCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_feed_now"

    async def async_press(self) -> None:
        await self.coordinator.async_feed()
