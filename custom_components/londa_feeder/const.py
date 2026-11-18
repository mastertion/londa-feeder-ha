"""Constants for the LONDA fish feeder integration."""

DOMAIN = "londa_feeder"

# --- 连接参数 ---
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_ADDRESS = "address"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_NAME = "name"

# --- DP 映射 ---
CONF_FEED_DP = "feed_dp"
CONF_FEED_IS_BOOL = "feed_is_bool"
CONF_PORTION_DP = "portion_dp"
CONF_BATTERY_DP = "battery_dp"
CONF_NO_FOOD_DP = "no_food_dp"
CONF_JAM_DP = "jam_dp"
CONF_FEEDING_DP = "feeding_dp"
CONF_PORTIONS = "portions"

# --- 默认值 ---
DEFAULT_NAME = "LONDA 喂食器"
AUTO_VERSION = "auto"
# 探测顺序：这台喂食器广播是 3.5，所以从 3.5 开始降级
PROBE_VERSIONS = (3.5, 3.4, 3.3, 3.1)
DEFAULT_PROTOCOL_VERSION = AUTO_VERSION
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_PORTIONS = 1
MIN_PORTIONS = 1
MAX_PORTIONS = 12

PROTOCOL_VERSIONS = [AUTO_VERSION, "3.5", "3.4", "3.3", "3.1"]
