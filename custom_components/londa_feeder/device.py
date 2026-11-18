"""Thin blocking wrapper around a Tuya LAN device (6668/TCP).

All methods are synchronous and are meant to be run inside
``hass.async_add_executor_job``. A single instance is reused for the whole
lifetime of a config entry so that the TCP socket can be kept alive
(tinytuya ``persist=True``).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)

# tinytuya 在这些键里返回错误而不是 dps
_ERROR_KEYS = ("Error", "Err", "error")


class LondaDeviceError(Exception):
    """设备通讯失败（不可达 / 认证错误）。"""


class LondaDevice:
    """一个涂鸦局域网设备。线程安全（内部加锁）。"""

    def __init__(
        self,
        device_id: str,
        address: str,
        local_key: str,
        version: float = 3.4,
        port: int = 6668,
    ) -> None:
        self._lock = threading.Lock()
        self._device_id = device_id
        self._address = address
        self._local_key = local_key
        self._version = version
        self._port = port
        self._dev = self._build()

    def _build(self) -> tinytuya.Device:
        dev = tinytuya.Device(
            self._device_id,
            self._address,
            self._local_key,
            version=self._version,
            persist=True,
            connection_timeout=5,
            port=self._port,
        )
        # 这台喂食器回包慢（实测 5~8 秒），超时放宽避免误判失败
        dev.set_socketTimeout(8)
        dev.set_socketRetryLimit(3)
        dev.set_sendWait(8)
        return dev

    # ------------------------------------------------------------------ #
    @staticmethod
    def _raise_if_error(payload: Any) -> None:
        if payload is None:
            raise LondaDeviceError("设备无响应")
        if isinstance(payload, dict):
            for key in _ERROR_KEYS:
                if key in payload:
                    raise LondaDeviceError(str(payload[key]))

    def poll(self) -> dict[str, Any]:
        """读取全部 DP，返回 ``{"1": true, "2": 3, ...}``。"""
        with self._lock:
            try:
                payload = self._dev.status()
                self._raise_if_error(payload)
                return dict(payload.get("dps") or {})
            except LondaDeviceError:
                # 连接可能已陈旧，重建一次再试
                self._safe_close()
                self._dev = self._build()
                payload = self._dev.status()
                self._raise_if_error(payload)
                return dict(payload.get("dps") or {})

    def probe(self) -> dict[str, Any]:
        """配置流程用：探测设备并返回 DP 快照。"""
        with self._lock:
            payload = self._dev.status()
            self._raise_if_error(payload)
            dps = dict(payload.get("dps") or {})
            if not dps:
                for _ in range(3):
                    self._dev.updatedps()
                    payload = self._dev.status()
                    if isinstance(payload, dict) and payload.get("dps"):
                        dps = dict(payload["dps"])
                        break
            return dps

    def _send(self, values: dict[str, Any], nowait: bool) -> None:
        if len(values) > 1:
            payload = self._dev.set_multiple_values(values, nowait=nowait)
        else:
            dp, val = next(iter(values.items()))
            payload = self._dev.set_value(dp, val, nowait=nowait)
        if nowait:
            _LOGGER.info("下发 DP %s（不等待回执）", values)
            return
        _LOGGER.info("下发 DP %s，回执 %s", values, str(payload)[:160])
        self._raise_if_error(payload)

    def set(self, values: dict[str, Any], nowait: bool = False) -> None:
        """下发 DP。

        先强制重建会话：设备会主动断开空闲连接，沿用旧 socket 会导致命令静默丢失。
        默认等待回执（本机实测设备 5~8 秒才 ACK）。
        """
        if not values:
            return
        with self._lock:
            self._safe_close()
            self._dev = self._build()
            try:
                self._send(values, nowait)
            except Exception as err:  # noqa: BLE001 - 重建后重发一次
                _LOGGER.warning("下发失败（%s），重建连接后重试", type(err).__name__)
                self._safe_close()
                self._dev = self._build()
                self._send(values, nowait)

    def _safe_close(self) -> None:
        try:
            self._dev.close()
        except Exception:  # noqa: BLE001 - 关闭失败无需处理
            pass

    def close(self) -> None:
        with self._lock:
            self._safe_close()
