"""Config flow for the LONDA fish feeder.

两条入口：
1. 扫码添加（推荐）：输入 APP 里的 User Code → 显示二维码 → 用 Londa APP 扫码授权
   → 自动拉取账号下设备 → 选择设备 → 自动解析局域网 IP 与 localKey。
2. 手动填写：直接给 IP / Device ID / Local Key（离线或扫码不可用时使用）。
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    AUTO_VERSION,
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
    CONF_PROTOCOL_VERSION,
    DEFAULT_NAME,
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    PROBE_VERSIONS,
    PROTOCOL_VERSIONS,
)
from .device import LondaDevice, LondaDeviceError

_LOGGER = logging.getLogger(__name__)

NONE_OPTION = "不使用"

# 与官方 Tuya 集成一致的授权参数（涂鸦给 Home Assistant 分配的应用）
TUYA_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
TUYA_SCHEMA = "haauthorize"
TUYA_DOMAIN = "tuya"
CONF_USER_CODE = "user_code"
CONF_QR_DEVICE = "qr_device"

DP_FIELDS = (
    CONF_FEED_DP,
    CONF_PORTION_DP,
    CONF_FEEDING_DP,
    CONF_BATTERY_DP,
    CONF_NO_FOOD_DP,
    CONF_JAM_DP,
)


def _sorted_dps(dps: dict[str, Any]) -> list[str]:
    return sorted(dps, key=lambda x: (len(str(x)), str(x)))


def _dp_options(dps: dict[str, Any]) -> list[selector.SelectOptionDict]:
    """把 DP 快照做成下拉选项，显示当前值便于辨认。"""
    return [
        selector.SelectOptionDict(
            value=str(dp), label=f"DP {dp} · 当前值 {dps[dp]!r}"
        )
        for dp in _sorted_dps(dps)
    ]


def _dp_select(
    options: list[selector.SelectOptionDict], allow_none: bool = True
) -> selector.SelectSelector:
    opts = list(options)
    if allow_none:
        opts.append(selector.SelectOptionDict(value=NONE_OPTION, label="不使用"))
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=opts, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _clean(value: str | None) -> str | None:
    if not value or value == NONE_OPTION:
        return None
    return value


def _dump_text(dps: dict[str, Any]) -> str:
    return "\n".join(f"DP {dp} = {dps[dp]!r}" for dp in _sorted_dps(dps))


def _qr_image_selector(qr_token: str) -> selector.QrCodeSelector:
    """二维码直接在配置界面里画出来，不需要外链图片。"""
    return selector.QrCodeSelector(
        config=selector.QrCodeSelectorConfig(
            data=f"tuyaSmart--qrLogin?token={qr_token}",
            scale=5,
            error_correction_level=selector.QrErrorCorrectionLevel.QUARTILE,
        )
    )


def _lan_scan() -> dict[str, dict[str, Any]]:
    """UDP 广播扫描局域网里的涂鸦设备。"""
    import tinytuya  # noqa: PLC0415

    result = tinytuya.deviceScan(False, 18) or {}
    return result if isinstance(result, dict) else {}


def _cloud_devices(
    user_code: str,
    terminal_id: str,
    endpoint: str,
    token_info: dict[str, Any],
) -> list[dict[str, Any]]:
    """用授权令牌拉取账号下的设备列表。

    token_info 与 login_result / 官方 tuya 条目的字段一致：
    t / uid / expire_time / access_token / refresh_token。
    """
    from tuya_sharing import Manager  # noqa: PLC0415

    manager = Manager(
        TUYA_CLIENT_ID,
        user_code,
        terminal_id,
        endpoint,
        token_response={
            "t": token_info["t"],
            "uid": token_info["uid"],
            "expire_time": token_info["expire_time"],
            "access_token": token_info["access_token"],
            "refresh_token": token_info["refresh_token"],
        },
    )
    manager.update_device_cache()

    devices: list[dict[str, Any]] = []
    for dev in manager.device_map.values():
        devices.append(
            {
                "id": dev.id,
                "name": getattr(dev, "name", None) or dev.id,
                "category": getattr(dev, "category", "") or "",
                "product_id": getattr(dev, "product_id", "") or "",
                "product_name": getattr(dev, "product_name", "") or "",
                "local_key": getattr(dev, "local_key", "") or "",
                "ip": getattr(dev, "ip", "") or "",
                "online": bool(getattr(dev, "online", False)),
            }
        )
    devices.sort(key=lambda d: (not d["online"], d["name"]))
    return devices


async def _probe_device(
    hass, device_id: str, address: str, local_key: str, version: str
) -> tuple[dict[str, Any], float | None, Exception | None]:
    """连接设备取 DP 快照；version 为 auto 时按 3.5→3.4→3.3→3.1 依次探测。"""
    candidates = PROBE_VERSIONS if str(version) == AUTO_VERSION else (float(version),)
    last_error: Exception | None = None

    for candidate in candidates:
        device = LondaDevice(
            device_id=device_id,
            address=address,
            local_key=local_key,
            version=candidate,
        )
        try:
            dps = await hass.async_add_executor_job(device.probe) or {}
        except Exception as err:  # noqa: BLE001
            last_error = err
            _LOGGER.debug("协议 %.1f 连接失败: %s", candidate, err)
        else:
            if dps:
                _LOGGER.info("喂食器连接成功，协议版本 %.1f，共 %d 个 DP", candidate, len(dps))
                return dps, candidate, None
            last_error = LondaDeviceError("设备返回了空 DP 列表")
        finally:
            await hass.async_add_executor_job(device.close)

    return {}, None, last_error


def _version_selector() -> selector.SelectSelector:
    labels = {
        AUTO_VERSION: "自动探测（推荐）",
        "3.5": "3.5",
        "3.4": "3.4",
        "3.3": "3.3",
        "3.1": "3.1",
    }
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=v, label=labels.get(v, v))
                for v in PROTOCOL_VERSIONS
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _tuya_entry_data(hass) -> dict[str, Any] | None:
    """读取 HA 里已有 Tuya 条目的授权信息（user_code + 令牌）。"""
    for entry in hass.config_entries.async_entries(TUYA_DOMAIN):
        data = entry.data or {}
        if data.get("user_code") and data.get("token_info"):
            return data
    return None


class LondaFeederConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """配置流程。"""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._dps: dict[str, Any] = {}
        self._user_code: str = ""
        self._qr_token: str = ""
        self._login_info: dict[str, Any] = {}
        self._cloud_devices: list[dict[str, Any]] = []
        self._qr_error_code: str = ""
        self._qr_error_msg: str = ""
        self._login_control = None

    # ---------- 入口 ----------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """选择添加方式。"""
        return self.async_show_menu(
            step_id="user",
            menu_options=["account", "qr"],
        )

    # ---------- 直接用已有授权 ----------

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """复用 HA 里已授权的 Tuya 账号，直接列设备。"""
        errors: dict[str, str] = {}

        if self._cloud_devices:
            return await self.async_step_qr_pick()

        entry_data = _tuya_entry_data(self.hass)
        if not entry_data:
            errors["base"] = "no_tuya_entry"
        else:
            try:
                devices = await self.hass.async_add_executor_job(
                    _cloud_devices,
                    entry_data["user_code"],
                    entry_data["terminal_id"],
                    entry_data["endpoint"],
                    entry_data["token_info"],
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("读取已有授权设备列表失败: %s", err)
                errors["base"] = "cloud_error"
            else:
                if devices:
                    self._cloud_devices = devices
                    return await self.async_step_qr_pick()
                errors["base"] = "no_devices"

        return self.async_show_form(step_id="account", errors=errors)

    def _async_make_qr(self, control, user_code: str) -> dict[str, Any]:
        return control.qr_code(TUYA_CLIENT_ID, TUYA_SCHEMA, user_code)

    # ---------- 扫码路径 ----------

    async def async_step_qr(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """生成二维码。已有 Tuya 授权时自动带上 user_code，无需手填。"""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        from tuya_sharing import LoginControl  # noqa: PLC0415

        if user_input is not None:
            self._user_code = (user_input.get(CONF_USER_CODE) or "").strip()
        elif self._user_code:
            pass
        else:
            stored = _tuya_entry_data(self.hass)
            if stored:
                self._user_code = stored["user_code"]

        if self._user_code:
            control = LoginControl()
            response = await self.hass.async_add_executor_job(
                self._async_make_qr, control, self._user_code
            )
            if response.get("success"):
                self._login_control = control
                self._qr_token = response["result"]["qrcode"]
                return await self.async_step_qr_scan()

            errors["base"] = "invalid_user_code"
            placeholders = {
                "msg": str(response.get("msg", "Unknown error")),
                "code": str(response.get("code", "0")),
            }
        elif user_input is not None:
            errors[CONF_USER_CODE] = "required"

        return self.async_show_form(
            step_id="qr",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USER_CODE,
                        default=(user_input or {}).get(CONF_USER_CODE, ""),
                    ): cv.string,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_qr_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """展示二维码，扫码后点提交完成授权。"""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            ok, info = await self.hass.async_add_executor_job(
                self._login_control.login_result,
                self._qr_token,
                TUYA_CLIENT_ID,
                self._user_code,
            )
            if ok:
                self._login_info = info
                try:
                    self._cloud_devices = await self.hass.async_add_executor_job(
                        _cloud_devices,
                        self._user_code,
                        info["terminal_id"],
                        info["endpoint"],
                        info,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.exception("拉取设备列表失败: %s", err)
                    errors["base"] = "cloud_error"
                else:
                    if not self._cloud_devices:
                        errors["base"] = "no_devices"
                    else:
                        return await self.async_step_qr_pick()
            else:
                # 二维码可能已过期，重新申请一张
                response = await self.hass.async_add_executor_job(
                    self._async_make_qr, self._login_control, self._user_code
                )
                if response.get("success"):
                    self._qr_token = response["result"]["qrcode"]
                errors["base"] = "qr_not_scanned"
                placeholders = {"msg": str(info.get("msg", "Unknown error"))}

        return self.async_show_form(
            step_id="qr_scan",
            data_schema=vol.Schema({vol.Optional("QR"): _qr_image_selector(self._qr_token)}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_qr_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """从账号设备列表里挑一台。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            chosen = user_input.get(CONF_QR_DEVICE)
            device = next(
                (d for d in self._cloud_devices if d["id"] == chosen), None
            )
            if device is None:
                errors["base"] = "unknown"
            else:
                address = await self._async_resolve_address(device["id"])
                if not address:
                    errors["base"] = "device_not_found"
                else:
                    await self.async_set_unique_id(device["id"].lower())
                    self._abort_if_unique_id_configured()

                    dps, detected, err = await _probe_device(
                        self.hass,
                        device["id"],
                        address,
                        device["local_key"],
                        AUTO_VERSION,
                    )
                    if not dps:
                        _LOGGER.warning("扫码选中的设备本地连接失败: %s", err)
                        errors["base"] = "cannot_connect"
                    else:
                        self._data = {
                            CONF_DEVICE_ID: device["id"],
                            CONF_ADDRESS: address,
                            CONF_LOCAL_KEY: device["local_key"],
                            CONF_PROTOCOL_VERSION: f"{detected}",
                            CONF_NAME: (device["name"] or DEFAULT_NAME).strip(),
                        }
                        self._dps = dps
                        return await self.async_step_dp_map()

        options = [
            selector.SelectOptionDict(
                value=d["id"],
                label=(
                    f"{d['name']} · {d['category'] or '未知品类'} · "
                    f"{'在线' if d['online'] else '离线'}"
                ),
            )
            for d in self._cloud_devices
        ]
        return self.async_show_form(
            step_id="qr_pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_QR_DEVICE, default=options[0]["value"]): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_resolve_address(self, device_id: str) -> str | None:
        """局域网广播找设备 IP（云端返回的 ip 通常是公网出口，不能用）。"""
        try:
            scan = await self.hass.async_add_executor_job(_lan_scan)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("局域网扫描失败: %s", err)
            return None

        for ip, info in scan.items():
            if str(info.get("gwId", "")).lower() == device_id.lower():
                _LOGGER.info("已定位设备 %s -> %s", device_id, ip)
                return ip
        _LOGGER.warning("局域网内未找到设备 %s（扫描到 %d 台）", device_id, len(scan))
        return None

    # ---------- 手动路径 ----------

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            address = user_input[CONF_ADDRESS].strip()
            local_key = user_input[CONF_LOCAL_KEY].strip()

            await self.async_set_unique_id(device_id.lower())
            self._abort_if_unique_id_configured()

            dps, detected, err = await _probe_device(
                self.hass,
                device_id,
                address,
                local_key,
                str(user_input[CONF_PROTOCOL_VERSION]),
            )

            if not dps:
                if err:
                    _LOGGER.warning("连接喂食器失败: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    errors["base"] = "no_dps"
            else:
                self._data = {
                    CONF_DEVICE_ID: device_id,
                    CONF_ADDRESS: address,
                    CONF_LOCAL_KEY: local_key,
                    CONF_PROTOCOL_VERSION: f"{detected}",
                    CONF_NAME: (user_input.get(CONF_NAME) or DEFAULT_NAME).strip(),
                }
                self._dps = dps
                return await self.async_step_dp_map()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Required(CONF_ADDRESS): cv.string,
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(CONF_LOCAL_KEY): cv.string,
                vol.Required(
                    CONF_PROTOCOL_VERSION, default=str(DEFAULT_PROTOCOL_VERSION)
                ): _version_selector(),
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    # ---------- DP 映射 ----------

    async def async_step_dp_map(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """让用户指认每个 DP 的用途。"""
        options = _dp_options(self._dps)

        if user_input is not None:
            feed_dp = user_input.get(CONF_FEED_DP)
            if feed_dp in (None, NONE_OPTION):
                return self.async_show_form(
                    step_id="dp_map",
                    data_schema=self._dp_schema(options),
                    errors={CONF_FEED_DP: "required"},
                    description_placeholders={"dump": _dump_text(self._dps)},
                )
            opts = {
                CONF_FEED_DP: feed_dp,
                CONF_FEED_IS_BOOL: isinstance(self._dps.get(feed_dp), bool),
            }
            for key in DP_FIELDS[1:]:
                opts[key] = _clean(user_input.get(key))
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=opts
            )

        guess = next(
            (dp for dp in _sorted_dps(self._dps) if isinstance(self._dps[dp], bool)),
            _sorted_dps(self._dps)[0],
        )
        return self.async_show_form(
            step_id="dp_map",
            data_schema=self._dp_schema(options, feed_default=guess),
            description_placeholders={"dump": _dump_text(self._dps)},
        )

    def _dp_schema(
        self,
        options: list[selector.SelectOptionDict],
        feed_default: str | None = None,
    ) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_FEED_DP, default=feed_default or options[0]["value"]
                ): _dp_select(options, allow_none=False),
                vol.Optional(CONF_PORTION_DP, default=NONE_OPTION): _dp_select(options),
                vol.Optional(CONF_FEEDING_DP, default=NONE_OPTION): _dp_select(options),
                vol.Optional(CONF_BATTERY_DP, default=NONE_OPTION): _dp_select(options),
                vol.Optional(CONF_NO_FOOD_DP, default=NONE_OPTION): _dp_select(options),
                vol.Optional(CONF_JAM_DP, default=NONE_OPTION): _dp_select(options),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return LondaFeederOptionsFlow()


class LondaFeederOptionsFlow(config_entries.OptionsFlow):
    """后续修改 DP 映射（HA 2024.11+ 的 self.config_entry 写法）。"""

    def __init__(self) -> None:
        self._dps: dict[str, Any] = {}
        self._error: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        cfg = {**entry.data, **entry.options}

        if user_input is not None:
            feed_dp = user_input.get(CONF_FEED_DP)
            if feed_dp in (None, NONE_OPTION):
                self._error = "required"
            else:
                opts = {
                    CONF_FEED_DP: feed_dp,
                    CONF_FEED_IS_BOOL: isinstance(self._dps.get(feed_dp), bool),
                }
                for key in DP_FIELDS[1:]:
                    opts[key] = _clean(user_input.get(key))
                return self.async_create_entry(title="", data=opts)

        dps, _detected, err = await _probe_device(
            self.hass,
            cfg[CONF_DEVICE_ID],
            cfg[CONF_ADDRESS],
            cfg[CONF_LOCAL_KEY],
            str(cfg.get(CONF_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION)),
        )
        if dps:
            self._dps = dps
        else:
            _LOGGER.warning("options 流程探测设备失败（%s），回退到已有 DP 列表", err)
            self._dps = {
                dp: None for dp in (cfg.get(k) for k in DP_FIELDS) if dp
            }

        options = _dp_options(self._dps) or [
            selector.SelectOptionDict(value="1", label="DP 1")
        ]
        feed_default = cfg.get(CONF_FEED_DP) or options[0]["value"]

        schema = vol.Schema(
            {
                vol.Required(CONF_FEED_DP, default=feed_default): _dp_select(
                    options, allow_none=False
                ),
                vol.Optional(
                    CONF_PORTION_DP, default=cfg.get(CONF_PORTION_DP) or NONE_OPTION
                ): _dp_select(options),
                vol.Optional(
                    CONF_FEEDING_DP, default=cfg.get(CONF_FEEDING_DP) or NONE_OPTION
                ): _dp_select(options),
                vol.Optional(
                    CONF_BATTERY_DP, default=cfg.get(CONF_BATTERY_DP) or NONE_OPTION
                ): _dp_select(options),
                vol.Optional(
                    CONF_NO_FOOD_DP, default=cfg.get(CONF_NO_FOOD_DP) or NONE_OPTION
                ): _dp_select(options),
                vol.Optional(
                    CONF_JAM_DP, default=cfg.get(CONF_JAM_DP) or NONE_OPTION
                ): _dp_select(options),
            }
        )
        errors = {CONF_FEED_DP: self._error} if self._error else {}
        self._error = None
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"dump": _dump_text(self._dps)},
        )
