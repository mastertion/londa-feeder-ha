"""Data coordinator: polls the feeder over the local Tuya protocol."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS,
    CONF_BATTERY_DP,
    CONF_DEVICE_ID,
    CONF_FEED_DP,
    CONF_FEED_IS_BOOL,
    CONF_FEEDING_DP,
    CONF_JAM_DP,
    CONF_LOCAL_KEY,
    CONF_NAME,
    CONF_NO_FOOD_DP,
    CONF_PORTION_DP,
    CONF_PORTIONS,
    CONF_PROTOCOL_VERSION,
    DEFAULT_NAME,
    DEFAULT_PORTIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_PORTIONS,
    MIN_PORTIONS,
)
from .device import LondaDevice, LondaDeviceError

_LOGGER = logging.getLogger(__name__)


def _safe_version(value: Any) -> float:
    """配置里可能残留 "auto"，此时回落到 3.4（3.5 设备通常也接受 3.4 帧）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        _LOGGER.debug("协议版本 %r 无法解析，回落到 3.4", value)
        return 3.4


class LondaFeederCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """统一刷新设备 DP 快照。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = {**entry.data, **entry.options}
        self.device = LondaDevice(
            device_id=cfg[CONF_DEVICE_ID],
            address=cfg[CONF_ADDRESS],
            local_key=cfg[CONF_LOCAL_KEY],
            version=_safe_version(cfg.get(CONF_PROTOCOL_VERSION)),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{cfg.get(CONF_NAME, DEFAULT_NAME)}",
            update_interval=timedelta(
                seconds=cfg.get("scan_interval", DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.config = cfg
        self._attr_name = cfg.get(CONF_NAME, DEFAULT_NAME)
        self._entry = entry

    # ------------------------------------------------------------------ #
    # DP 配置
    # ------------------------------------------------------------------ #
    @property
    def feed_dp(self) -> str | None:
        return self.config.get(CONF_FEED_DP) or None

    @property
    def portion_dp(self) -> str | None:
        return self.config.get(CONF_PORTION_DP) or None

    @property
    def battery_dp(self) -> str | None:
        return self.config.get(CONF_BATTERY_DP) or None

    @property
    def no_food_dp(self) -> str | None:
        return self.config.get(CONF_NO_FOOD_DP) or None

    @property
    def jam_dp(self) -> str | None:
        return self.config.get(CONF_JAM_DP) or None

    @property
    def feeding_dp(self) -> str | None:
        """设备上报"正在投喂"状态的 DP（只读）。"""
        return self.config.get(CONF_FEEDING_DP) or None

    @property
    def portions(self) -> int:
        """每次投喂份数：存在条目选项里，不直接写设备。"""
        try:
            value = int(self.config.get(CONF_PORTIONS, DEFAULT_PORTIONS))
        except (TypeError, ValueError):
            return DEFAULT_PORTIONS
        return max(MIN_PORTIONS, min(MAX_PORTIONS, value))

    @property
    def feed_is_bool(self) -> bool:
        return bool(self.config.get(CONF_FEED_IS_BOOL, True))

    def dp_value(self, dp: str | None, default: Any = None) -> Any:
        if not dp or not self.data:
            return default
        return self.data.get(str(dp), default)

    # ------------------------------------------------------------------ #
    # 刷新
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.hass.async_add_executor_job(self.device.poll)
        except LondaDeviceError as err:
            self.device_reachable = False
            raise UpdateFailed(f"设备不可达: {err}") from err
        except Exception as err:  # noqa: BLE001 - tinytuya 可能抛出各种异常
            self.device_reachable = False
            raise UpdateFailed(f"读取设备失败: {err}") from err

        self.device_reachable = True
        if not data:
            raise UpdateFailed("设备返回空状态")
        return data

    device_reachable: bool = False

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    async def async_feed(self, portions: int | None = None) -> None:
        """手动投喂一次。"""
        values: dict[str, Any] = {}
        if portions is None:
            portions = self.portions

        if self.portion_dp and self.portion_dp != self.feed_dp:
            values[self.portion_dp] = int(portions)

        if self.feed_dp:
            values[self.feed_dp] = True if self.feed_is_bool else int(portions)
        elif self.portion_dp:
            values[self.portion_dp] = True
        else:
            raise LondaDeviceError("未配置投喂 DP")

        await self.hass.async_add_executor_job(self.device.set, values)
        # 这台设备下发到真正出粮有 6~25 秒延迟，安排两次延后刷新把状态抓稳
        self.hass.async_create_task(self._async_refresh_later(15.0))
        self.hass.async_create_task(self._async_refresh_later(35.0))

    async def _async_refresh_later(self, delay: float = 15.0) -> None:
        import asyncio

        await asyncio.sleep(delay)
        await self.async_request_refresh()

    async def async_set_portions(self, portions: int) -> None:
        """保存"每次投喂份数"到条目选项（不写设备，避免立刻出粮）。"""
        value = max(MIN_PORTIONS, min(MAX_PORTIONS, int(portions)))
        options = {**self._entry.options, CONF_PORTIONS: value}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.config = {**self._entry.data, **self._entry.options}
        self.async_set_updated_data(self.data or {})


    async def async_shutdown(self) -> None:
        await self.hass.async_add_executor_job(self.device.close)
