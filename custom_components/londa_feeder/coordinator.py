"""Data coordinator: polls the feeder over the local Tuya protocol."""

from __future__ import annotations

import logging
from datetime import timedelta
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
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
    STORAGE_KEY,
    STORAGE_VERSION,
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

        # 投喂统计（用于「本次投喂份数」传感器）
        self.last_feed_portions: int | None = None
        self.last_feed_at: datetime | None = None
        self.feed_count: int = 0
        self._prev_feed_raw: Any = None
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.{STORAGE_KEY}"
        )

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
    device_reachable: bool = False

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
        self._track_feed_report(data)
        return data

    # ------------------------------------------------------------------ #
    # 投喂份数统计
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_active_feed(raw: Any) -> bool:
        """DP 上报是否表示"这一次投喂携带了份数"。"""
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw > 0
        return False

    def _record_feed(self, portions: int) -> None:
        self.last_feed_portions = max(0, int(portions))
        self.last_feed_at = datetime.now(timezone.utc)
        self.feed_count += 1
        self._schedule_save()
        self.async_set_updated_data(self.data or {})

    # ------------------------------------------------------------------ #
    # 持久化：重启后仍能看到上次投喂份数与累计次数
    # ------------------------------------------------------------------ #
    async def async_load_stats(self) -> None:
        """从 .storage 恢复上次投喂记录。"""
        try:
            stored = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - 读失败不影响主流程
            _LOGGER.debug("读取投喂统计失败: %s", err)
            return
        if not isinstance(stored, dict):
            return
        portions = stored.get("last_feed_portions")
        if isinstance(portions, (int, float)) and not isinstance(portions, bool):
            self.last_feed_portions = int(portions)
        stamp = stored.get("last_feed_at")
        if isinstance(stamp, str) and stamp:
            try:
                self.last_feed_at = datetime.fromisoformat(stamp)
            except ValueError:
                _LOGGER.debug("投喂时间 %r 无法解析", stamp)
        count = stored.get("feed_count")
        if isinstance(count, (int, float)) and not isinstance(count, bool):
            self.feed_count = int(count)

    def _schedule_save(self) -> None:
        self.hass.async_create_task(self._async_save_stats())

    async def _async_save_stats(self) -> None:
        payload = {
            "last_feed_portions": self.last_feed_portions,
            "last_feed_at": (
                self.last_feed_at.isoformat() if self.last_feed_at else None
            ),
            "feed_count": self.feed_count,
        }
        try:
            await self._store.async_save(payload)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("保存投喂统计失败: %s", err)

    def _track_feed_report(self, data: dict[str, Any]) -> None:
        """设备上报 DP6=N 后归零：抓到一次"出粮 N 份"。"""
        if not self.feed_dp:
            return
        raw = data.get(str(self.feed_dp))
        active = self._is_active_feed(raw)
        prev_active = self._is_active_feed(self._prev_feed_raw)
        self._prev_feed_raw = raw
        if not active or prev_active:
            return
        portions = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else self.portions
        # 命令下发时已经乐观记过一次，这里只补正份数、避免重复计数
        if (
            self.last_feed_portions is not None
            and self.last_feed_at is not None
            and (datetime.now(timezone.utc) - self.last_feed_at).total_seconds() < 120
        ):
            self.last_feed_portions = max(0, portions)
            self._schedule_save()
            self.async_set_updated_data(self.data or {})
            return
        self._record_feed(portions)

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
        # 立即乐观更新份数与次数，界面不用等出粮那 6~25 秒
        self.last_feed_portions = int(portions)
        self.last_feed_at = datetime.now(timezone.utc)
        self.feed_count += 1
        self._schedule_save()
        self.async_set_updated_data(self.data or {})
        # 设备真正出粮有 6~25 秒延迟、"投喂中"只亮约 9 秒，多点采样才抓得稳
        for delay in (8.0, 20.0, 40.0):
            self.hass.async_create_task(self._async_refresh_later(delay))

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
