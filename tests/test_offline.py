# -*- coding: utf-8 -*-
"""离线自测：用桩替代 HA 依赖，导入集成并验证关键逻辑。

只验证纯逻辑与导入完整性，不需要真的安装 Home Assistant。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # .../londa-feeder-ha
sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# 1. 构造 homeassistant 桩
# --------------------------------------------------------------------------- #
def _mod(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _ConfigEntry:
    def __init__(self, data=None, options=None, entry_id="test"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id

    def async_on_unload(self, _fn):
        pass

    def add_update_listener(self, _fn):
        pass


class _ConfigFlow:
    VERSION = 1

    def __init_subclass__(cls, domain=None, **kw):
        super().__init_subclass__(**kw)


class _OptionsFlow:
    def __init__(self, *a, **k):
        self.config_entry = _ConfigEntry()


class _CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


class _DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name=None, update_interval=None):
        self.hass = hass
        self.name = name
        self.data = {}
        self.update_interval = update_interval

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def async_request_refresh(self):
        pass

    async def async_shutdown(self):
        pass

    async def _async_update_data(self):
        return {}


class _UpdateFailed(Exception):
    pass


class _FlowResult(dict):
    pass


class _Selector:
    class SelectSelectorConfig:
        def __init__(self, **kw):
            self.kw = kw

    def __init__(self, config=None):
        self.config = config

    def __call__(self, value):
        return value


class _SelectorNS:
    SelectSelector = _Selector
    SelectOptionDict = dict
    SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown")


class _CV:
    string = str


_MODULES = {
    "homeassistant": {},
    "homeassistant.components": {},
    "homeassistant.config_entries": dict(
        ConfigEntry=_ConfigEntry, ConfigFlow=_ConfigFlow, OptionsFlow=_OptionsFlow
    ),
    "homeassistant.core": dict(HomeAssistant=object, callback=lambda f: f),
    "homeassistant.data_entry_flow": dict(FlowResult=_FlowResult),
    "homeassistant.const": dict(Platform=types.SimpleNamespace(
        BUTTON="button", SENSOR="sensor", BINARY_SENSOR="binary_sensor", NUMBER="number"
    ), PERCENTAGE="%"),
    "homeassistant.exceptions": dict(ConfigEntryNotReady=Exception),
    "homeassistant.helpers": {},
    "homeassistant.helpers.config_validation": dict(string=str),
    "homeassistant.helpers.selector": None,      # 需保留模块语义
    "homeassistant.helpers.device_registry": dict(DeviceInfo=dict),
    "homeassistant.helpers.entity_platform": dict(AddEntitiesCallback=object),
    "homeassistant.helpers.update_coordinator": dict(
        DataUpdateCoordinator=_DataUpdateCoordinator,
        CoordinatorEntity=_CoordinatorEntity,
        UpdateFailed=_UpdateFailed,
    ),
    "homeassistant.components.button": dict(ButtonEntity=object),
    "homeassistant.components.sensor": dict(
        SensorEntity=object,
        SensorDeviceClass=types.SimpleNamespace(BATTERY="battery"),
        SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement"),
    ),
    "homeassistant.components.binary_sensor": dict(
        BinarySensorEntity=object,
        BinarySensorDeviceClass=types.SimpleNamespace(PROBLEM="problem", RUNNING="running"),
    ),
    "homeassistant.components.number": dict(
        NumberEntity=object,
        NumberMode=types.SimpleNamespace(BOX="box"),
    ),
}

for name, attrs in _MODULES.items():
    if attrs is None:
        _mod(name)
    else:
        _mod(name, **attrs)

# selector 模块需要属性
sel = sys.modules["homeassistant.helpers.selector"]
sel.SelectSelector = _Selector
sel.SelectSelectorConfig = _Selector.SelectSelectorConfig
sel.SelectOptionDict = dict
sel.SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown")

# 父包需要 __path__ 才能当作包导入
for pkg in ("homeassistant", "homeassistant.components", "homeassistant.helpers"):
    sys.modules[pkg].__path__ = []

import voluptuous  # noqa: E402

# --------------------------------------------------------------------------- #
# 2. 导入集成
# --------------------------------------------------------------------------- #
from custom_components.londa_feeder import const  # noqa: E402
from custom_components.londa_feeder import config_flow  # noqa: E402
from custom_components.londa_feeder.device import LondaDevice, LondaDeviceError  # noqa: E402
from custom_components.londa_feeder.binary_sensor import _is_problem  # noqa: E402
from custom_components.londa_feeder.number import _as_int  # noqa: E402
from custom_components.londa_feeder.sensor import _as_number  # noqa: E402
from custom_components.londa_feeder.coordinator import LondaFeederCoordinator  # noqa: E402

print("✓ 所有模块导入成功")

# --------------------------------------------------------------------------- #
# 3. 纯函数断言
# --------------------------------------------------------------------------- #
checks = []


def check(label, got, want):
    ok = got == want
    checks.append(ok)
    print(("  ✓ " if ok else "  ✗ ") + f"{label}: got={got!r} want={want!r}")


print("\n[缺粮/卡粮判定]")
check("bool True", _is_problem(True), True)
check("bool False", _is_problem(False), False)
check("int 1", _is_problem(1), True)
check("int 0", _is_problem(0), False)
check("'empty'", _is_problem("empty"), True)
check("'normal'", _is_problem("normal"), False)
check("'卡粮'", _is_problem("卡粮"), True)
check("None", _is_problem(None), None)

print("\n[数值解析]")
check("_as_int('3')", _as_int("3"), 3)
check("_as_int(True)", _as_int(True), None)
check("_as_int('3.7')", _as_int("3.7"), 3)
check("_as_number('85%')", _as_number("85%"), 85.0)
check("_as_number(True)", _as_number(True), None)

print("\n[DP 下拉选项]")
opts = config_flow._dp_options({"1": False, "10": 3, "2": "normal"})
check("选项数量", len(opts), 3)
check("排序(1,2,10)", [o["value"] for o in opts], ["1", "2", "10"])
check("_clean(不使用)", config_flow._clean("不使用"), None)
check("_clean('3')", config_flow._clean("3"), "3")

print("\n[Schema 可构建]")
schema = config_flow.LondaFeederConfigFlow._dp_schema(
    config_flow.LondaFeederConfigFlow.__new__(config_flow.LondaFeederConfigFlow),
    opts,
    feed_default="1",
)
check("schema 类型", isinstance(schema, voluptuous.Schema), True)

# --------------------------------------------------------------------------- #
# 4. 设备不可达路径
# --------------------------------------------------------------------------- #
print("\n[设备错误路径]")
dev = LondaDevice("dev123", "127.0.0.1", "0123456789abcdef", version=3.3)
try:
    dev.poll()
    print("  ✗ 应当抛出 LondaDeviceError")
    checks.append(False)
except LondaDeviceError as err:
    print(f"  ✓ 正确抛出 LondaDeviceError: {err}")
    checks.append(True)
finally:
    dev.close()

# --------------------------------------------------------------------------- #
# 5. coordinator 逻辑（不跑 IO）
# --------------------------------------------------------------------------- #
print("\n[coordinator DP 取值]")
coord = LondaFeederCoordinator.__new__(LondaFeederCoordinator)
coord.config = {
    const.CONF_FEED_DP: "1",
    const.CONF_PORTION_DP: "2",
    const.CONF_BATTERY_DP: "3",
    const.CONF_NO_FOOD_DP: "",
    const.CONF_JAM_DP: "5",
    const.CONF_FEED_IS_BOOL: True,
}
coord.data = {"1": False, "2": 3, "3": 85, "5": False}
check("feed_dp", coord.feed_dp, "1")
check("portion_dp", coord.portion_dp, "2")
check("no_food_dp(None)", coord.no_food_dp, None)
check("battery 值", coord.dp_value("3"), 85)
check("不存在 DP", coord.dp_value("9", "x"), "x")
check("feed_is_bool", coord.feed_is_bool, True)

print()
if all(checks):
    print(f"全部 {len(checks)} 项断言通过")
    sys.exit(0)
print(f"失败 {checks.count(False)} / {len(checks)} 项")
sys.exit(1)
