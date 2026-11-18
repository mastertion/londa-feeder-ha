#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LONDA / 涂鸦设备 localKey 提取 + DP 探测工具。

用法
----
1) 列出账号下所有设备（需要涂鸦开发者平台 Cloud 项目的 Access ID / Secret）：

    python tuya_localkey.py --key <AccessID> --secret <AccessSecret>

2) 查看某台设备的 DP 明细（本地直连，需要 IP + localKey）：

    python tuya_localkey.py --dump <device_id> --ip 192.168.1.50 --local-key <key>

3) 扫描局域网内的涂鸦设备（补全 IP）：

    python tuya_localkey.py --scan

说明：设备本身是涂鸦（ThingClips）方案，londa APP 只是 OEM 皮。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    import tinytuya
except ImportError:
    sys.exit("缺少依赖：pip install tinytuya")

REGIONS = ("cn", "us", "eu", "in", "sg", "us-e", "we", "ea", "wd")


def _print_table(rows: list[dict[str, Any]], cols: list[str]) -> None:
    if not rows:
        print("（空）")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def cmd_list(args: argparse.Namespace) -> int:
    cloud = tinytuya.Cloud(
        apiRegion=args.region,
        apiKey=args.key,
        apiSecret=args.secret,
        new_sign_algorithm=not args.legacy_sign,
    )
    devices = cloud.getdevices(verbose=True)
    if isinstance(devices, dict):
        print("云接口返回错误：", devices, file=sys.stderr)
        return 1

    rows = []
    for d in devices:
        rows.append(
            {
                "name": d.get("name", ""),
                "device_id": d.get("id", ""),
                "category": d.get("category", ""),
                "product": d.get("product_name", ""),
                "ip": d.get("ip", ""),
                "version": d.get("version", ""),
                "online": d.get("online", ""),
                "local_key": d.get("local_key") or d.get("key", ""),
            }
        )

    _print_table(
        rows,
        ["name", "device_id", "category", "product", "ip", "version", "online", "local_key"],
    )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.out}")

    print("\n把上面这台设备的 ip / device_id / local_key 填进 HA 集成即可。")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    found = tinytuya.deviceScan(False, args.timeout)
    for ip, info in found.items():
        print(f"{ip:<16} {info.get('gwId', ''):<24} ver={info.get('version', '')}")
    if not found:
        print("未发现设备。确认设备与电脑在同一局域网，且已配网成功。", file=sys.stderr)
    return 0


def _cloud_dp_names(args: argparse.Namespace, device_id: str) -> dict[str, str]:
    """用云接口拿 dp_id -> code 的中文/英文名，本地直连不需要它也能跑。"""
    if not (args.key and args.secret):
        return {}
    try:
        cloud = tinytuya.Cloud(
            apiRegion=args.region,
            apiKey=args.key,
            apiSecret=args.secret,
            new_sign_algorithm=not args.legacy_sign,
        )
        spec = cloud.getdps(device_id)
        result = (spec or {}).get("result") or {}
        mapping: dict[str, str] = {}
        for item in (result.get("status") or []) + (result.get("functions") or []):
            if "dp_id" in item and "code" in item:
                mapping[str(item["dp_id"])] = item["code"]
        return mapping
    except Exception as exc:  # noqa: BLE001
        print(f"（云接口取 DP 名称失败，忽略：{exc}）", file=sys.stderr)
        return {}


def cmd_dump(args: argparse.Namespace) -> int:
    dev = tinytuya.Device(
        args.dump,
        address=args.ip,
        local_key=args.local_key,
        version=float(args.version),
        persist=False,
    )
    dev.set_socketTimeout(5)
    payload = dev.status()
    if not isinstance(payload, dict) or "dps" not in payload:
        print("读取失败：", payload, file=sys.stderr)
        return 1

    dps = payload["dps"]
    names = _cloud_dp_names(args, args.dump)

    rows = [
        {
            "dp": dp,
            "code": names.get(str(dp), ""),
            "value": repr(val),
            "type": type(val).__name__,
        }
        for dp, val in sorted(dps.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999)
    ]
    _print_table(rows, ["dp", "code", "value", "type"])

    # 现场验证一次写值，帮用户确认哪个 DP 是"投喂触发"
    if args.try_feed:
        dp = args.try_feed
        guess = True if isinstance(dps.get(dp), bool) else 1
        print(f"\n尝试写入 DP {dp} = {guess!r} …")
        resp = dev.set_value(dp, guess)
        print("设备返回：", resp)
        print("若喂食器立即出粮，则这个 DP 就是投喂触发 DP。")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"dps": dps, "codes": names}, fh, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="LONDA/涂鸦设备 localKey 提取与 DP 探测")
    p.add_argument("--region", default="cn", choices=REGIONS, help="数据中心，国内填 cn")
    p.add_argument("--key", help="涂鸦 Cloud 项目 Access ID")
    p.add_argument("--secret", help="涂鸦 Cloud 项目 Access Secret")
    p.add_argument("--legacy-sign", action="store_true", help="老项目用旧签名算法时加上")
    p.add_argument("--out", help="把结果写成 JSON 文件")
    p.add_argument("--scan", action="store_true", help="扫描局域网涂鸦设备")
    p.add_argument("--timeout", type=int, default=18, help="扫描超时秒数")
    p.add_argument("--dump", metavar="DEVICE_ID", help="打印该设备的 DP 明细")
    p.add_argument("--ip", help="设备局域网 IP")
    p.add_argument("--local-key", dest="local_key", help="设备 localKey")
    p.add_argument("--version", default="3.4", help="协议版本，默认 3.4")
    p.add_argument("--try-feed", metavar="DP", help="试写一个 DP，验证是否为投喂触发")
    args = p.parse_args()

    if args.scan:
        return cmd_scan(args)
    if args.dump:
        if not (args.ip and args.local_key):
            p.error("--dump 需要同时提供 --ip 和 --local-key")
        return cmd_dump(args)
    if args.key and args.secret:
        return cmd_list(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
