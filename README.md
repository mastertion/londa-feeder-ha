# LONDA 鱼缸喂食器 · Home Assistant 集成

把 **LONDA（艾隆达）WiFi 鱼缸自动喂食器** 接入 Home Assistant，实现一键投喂、份数设置、备用电池电量与缺粮/卡粮告警。

---

## 先说结论：不用真的去逆向

对 `com.londa.smart_2.8.0.apk` 拆包后的结论：

| 观察点 | 结果 |
|---|---|
| 核心包名 | `com.thingclips.smart.dev` —— 涂鸦（Tuya / ThingClips）官方 SDK |
| 关键 so | `libThingSmartLink.so`、`libThingP2PSDK.so`、`libthingsmart.so`、`libThingCloudStorageSignatureTools.so` |
| 配网热点 | `assets/asset_resource.json` 中 `ap_mode_ssid = SmartLife` |
| 加固 | 无壳，dex 明文，共 10 个 dex |
| 配网引导 | 官方说明即为「扫码下载涂鸦 APP」 |

也就是说 **londa 只是涂鸦的白牌（OEM）APP**，设备走的是涂鸦通用协议：

- 云端：涂鸦统一的 OpenAPI
- 本地：TCP **6668**，AES-128 加密，协议 3.1 / 3.3 / 3.4 / 3.5

协议本身早已公开（`tinytuya`、`localtuya` 都实现了），所以逆向 APP 里那层壳没有收益，**唯一真正需要的东西只有 `localKey`**。本集成就是你拿到 localKey 之后的落地部分。

---

## 三条可选路线

| 路线 | 体验 | 需要什么 | 建议 |
|---|---|---|---|
| **本集成（本地直连）** | 局域网毫秒级，断网也能用 | IP + device_id + localKey | ✅ 推荐 |
| HACS 里的 `localtuya` | 功能更全，但配置项多 | 同上 | 想少写代码就走这个 |
| 涂鸦官方 `tuya` 云集成 | 免 localKey，但延迟 1–2 秒 | 涂鸦 IoT 开发者账号 | 只做简单联动时够用 |

本集成的价值：**专门为喂食器做了 DP 指认向导**，配置时直接把设备读到的 DP 快照列出来，你点几下就知道哪个是「投喂触发」，不用翻文档。

---

## 快速开始

### 第 1 步 · 拿 localKey（一次性，约 10 分钟）

**1.1 注册涂鸦开发者账号** → <https://iot.tuya.com>，右上角用手机号注册（**用你 londa APP 的同一个手机号**，后面绑定会顺很多）。

**1.2 创建 Cloud 项目**：`Cloud` → `Development` → `Create Cloud Project`

- 名称随意，如 `homeassistant`
- 数据中心选 **China**
- 创建后在项目里记下 **Access ID / Client ID** 和 **Access Secret**

**1.3 给项目授权 API**：项目详情 → `Service API` → 勾选并开通

- `IoT Core`（基础设备接口）
- `Authorization`（授权管理，绑定 APP 账号要用）
- `Device Control`（设备控制）
- `Device Management`（设备管理，取 DP 定义）

**1.4 关联你的 londa 账号**：项目 → `Devices` → `Link Tuya App Account` → `Add App Account`

会弹一个二维码，用 **londa APP**（或涂鸦/Smart Life）扫码并确认授权。成功后项目里就能看到你家设备。

**1.5 跑脚本取出全部参数**

```bash
pip install tinytuya
python tools/tuya_localkey.py --key <AccessID> --secret <AccessSecret> --out devices.json
```

输出形如：

```
name        device_id       category   product      ip            version  online  local_key
鱼缸喂食器   a1b2c3d4e5f6    cwtsq      鱼缸喂食器    192.168.1.50  3.4      True    U0j3k9Lm2Np...
```

> 如果 `ip` 是空的（设备上线时上报过但当前没记录），用 `python tools/tuya_localkey.py --scan` 扫描局域网补全。

### 第 2 步 · 装集成

仓库地址：**<https://github.com/mastertion/londa-feeder-ha>**

**方式 A · HACS 自定义仓库（推荐）**

1. HACS → 集成 → 右上角 `⋮` → **自定义仓库**
2. 仓库地址填 `https://github.com/mastertion/londa-feeder-ha`
3. 类别选 `Integration` → 添加
4. 在 HACS 里搜索「LONDA Feeder」安装（或直接点下载）
5. 重启 HA

**方式 B · git clone（命令行）**

```bash
cd /config/custom_components
git clone https://github.com/mastertion/londa-feeder-ha.git _tmp_londa
cp -r _tmp_londa/custom_components/londa_feeder ./londa_feeder
rm -rf _tmp_londa
```

然后重启 HA。后续更新直接 `git pull` 后再拷贝即可。

**方式 C · 手动 / 离线**

把 `custom_components/londa_feeder` 整个文件夹复制到 HA 的 `/config/custom_components/` 下，重启 HA。
（也可以用仓库根目录的 `londa_feeder.zip` 解压后放进去。）

### 第 3 步 · 添加设备（扫码 / 手动二选一）

`设置 → 设备与服务 → 添加集成 → 搜索 LONDA Feeder`

#### 方式 A · 直接用已有授权选设备（最快，零输入）

前提：HA 里已经配好官方 **Tuya** 集成（你已经有）。

1. 菜单选「使用已有涂鸦账号」
2. 集成用条目里存的授权去云端拉设备列表，**直接弹出选择框**（带品类、在线状态）
3. 选中喂食器后，自动在局域网广播里定位 IP、取 localKey、探测协议版本
4. 选投喂 DP（这台是 DP 6，「投喂中」是 DP 1）→ 完成

#### 方式 B · 扫码添加

1. 菜单选「扫码登录」
2. 已有 Tuya 条目时**自动带出 User Code**，直接画出二维码；没有则需手填（Londa APP：我的 → ⚙ → 账号与安全 → 最下方 User Code）
3. 用 **Londa APP** 右上角「+ → 扫一扫」扫码并在手机上确认
4. 回到 HA 点「提交」→ 列出设备 → 选喂食器 → 后续同上

#### 方式 C · 手动填写

填 **IP / Device ID / Local Key**，协议版本保持 **自动探测**（会按 3.5 → 3.4 → 3.3 → 3.1 依次尝试，连上即锁定版本）。
localKey 的取法见上面的第 1 步，或者直接从已有 Tuya 条目的授权里读（本集成本身不需要涂鸦开发者账号）。

> 局域网扫描要求 HA 与喂食器在**同一网段**，且 HA 容器使用 host 网络（HAOS 默认如此）。
> 扫描不到时会提示 `device_not_found`，此时改用方式 C 手填 IP 即可。

---

## 设备实体

| 实体 | 说明 |
|---|---|
| `button.xxx_feed_now` | 立即投喂（按一次下发投喂命令） |
| `binary_sensor.xxx_feeding` | 投喂中（设备上报，约亮 9 秒） |
| `number.xxx_portions_per_feed` | 每次投喂份数，1–12（只存 HA 侧，按按钮时才下发） |
| `sensor.xxx_battery` | 备用电池电量 %（仅当指定了电池 DP） |
| `binary_sensor.xxx_no_food` / `xxx_jam` | 缺粮 / 卡粮告警（仅当指定了对应 DP） |

### 喂食器常见 DP 参考

不同批次固件 DP 编号会变，**务必以配置向导里读到的实际值为准**（也可以 `--dump` 单独看）：

```bash
python tools/tuya_localkey.py --dump <device_id> --ip 192.168.1.50 --local-key <localKey>
```

```
dp   code          value   type
1    manual_feed   False   bool     ← 写 True 立即出粮
2    feed_num      3       int      ← 份数
3    battery       85      int      ← 备用电池
4    food_lack     False   bool     ← 缺粮
5    food_jam      False   bool     ← 卡粮
```

不确定哪个是投喂时，可以逐个试：

```bash
python tools/tuya_localkey.py --dump <device_id> --ip 192.168.1.50 --local-key <localKey> --try-feed 1
```

设备立刻出粮，说明 DP 1 就是投喂触发。

---

## 自动化示例

```yaml
automation:
  - alias: 每天早上 8 点喂鱼
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.li_yu_gang_wei_shi_qi_li_ji_tou_wei

  - alias: 缺粮提醒
    trigger:
      - platform: state
        entity_id: binary_sensor.li_yu_gang_wei_shi_qi_que_liang
        to: "on"
        for: "00:10:00"
    action:
      - service: notify.mobile_app
        data:
          message: 鱼缸喂食器食槽快空了
```

---

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| `cannot_connect` | IP 变了。给设备在路由器上做 **DHCP 静态绑定**，喂食器 IP 不固定是最大坑 |
| `cannot_connect` 但 IP 对 | localKey 抄错，或设备已被 APP 占用导致 local 连接被拒；先确认 Key，再试 3.3 / 3.1 |
| `no_dps` | 设备是**蓝牙版**，本集成只管 WiFi 型号 |
| 能读状态但按了没反应 | 投喂 DP 选错，回到集成选项里改 |
| 一段时间后全部实体变不可用 | 设备休眠/路由器踢下线。集成会自动重连，也可以把轮询间隔调大（默认 30 秒） |
| 脚本 `--key/--secret` 报权限错误 | 项目没开通 `IoT Core` + `Authorization` API，或数据中心选错（国内必须 `cn`） |

设备必须连 **2.4GHz WiFi**，这是涂鸦模组的硬限制。

---

## 目录结构

```
londa-feeder-ha/
├── custom_components/londa_feeder/
│   ├── __init__.py        集成入口
│   ├── config_flow.py     配置向导（连接 + DP 指认）
│   ├── coordinator.py     轮询与动作
│   ├── device.py          tinytuya 封装（含断线重连）
│   ├── entity.py          实体基类 / 设备信息
│   ├── button.py          立即投喂
│   ├── number.py          份数
│   ├── sensor.py          电量
│   ├── binary_sensor.py   缺粮 / 卡粮
│   ├── const.py
│   ├── manifest.json
│   ├── strings.json
│   └── translations/      en / zh-Hans
├── tools/tuya_localkey.py 取 localKey + 探测 DP
├── tests/test_offline.py  离线自测（桩替身，无需装 HA）
├── hacs.json
└── README.md
```

## 开发自测

```bash
python tests/test_offline.py     # 25 项断言，不需要安装 Home Assistant
```

---

## 免责声明

本项目仅用于**你自己拥有的设备**的本地互操作，不含任何破解、绕过授权或云端数据爬取逻辑。取 localKey 用的是涂鸦官方开发者接口，需要你本人账号授权。请勿将本项目用于他人设备。

## License

MIT

---

## 真机实测结论（2026-11-18）

设备：`(WiFi版)入门级喂食器` · product_id `dcxmtf1dv2chwmbw` · category `ygwsq`
网络：`192.168.3.101` · 协议 **3.5** · device_id `6ce8c0bdda2fa41a96qeq3`

这台设备本地只认两个 DP：

| DP | 类型 | 含义 | 读/写 |
|---|---|---|---|
| **1** | bool | 投喂中状态上报（true 约持续 9 秒） | 只读 |
| **6** | int | 投喂命令：写入 N 即投喂 N 份，随后自动归零 | 只写 |

三条必须知道的行为：

1. **下发到真正出粮有 6~25 秒延迟**，所以集成在投喂后 15s / 35s 各刷新一次状态。
2. **设备会主动断开空闲会话**，沿用旧 socket 会让命令静默丢失 → 集成每次下发前强制重建会话。
3. **同时只允许一个本地会话**，测试时另开一条连接会把 HA 的连接踢掉。

对应实体：

- `button.xxx_feed_now`：立即投喂（下发 DP6 = 份数）
- `binary_sensor.xxx_feeding`：投喂中
- `number.xxx_portions_per_feed`：每次投喂份数（只存 HA 侧，按按钮时才下发，不会一改就出粮）

> 云端 DP 定义为空（`function`/`status` 全空），所以官方 Tuya 集成永远出不来实体；本集成本地直连不受影响。
