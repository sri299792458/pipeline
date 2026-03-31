#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from pathlib import Path


SYS_USB_ROOT = Path("/sys/bus/usb/devices")
PCI_ADDR_PATTERN = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]", re.IGNORECASE)


@dataclass(frozen=True)
class UsbRootBus:
    bus_name: str
    busnum: int
    pci_controller: str
    usb_version: str
    root_speed_mbps: str
    max_ports: str


@dataclass(frozen=True)
class UsbDevice:
    sysfs_name: str
    busnum: int
    devnum: int
    root_bus_name: str
    pci_controller: str
    speed_mbps: str
    manufacturer: str
    product: str
    serial: str
    vendor_id: str
    product_id: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _pci_controller_for_path(path: Path) -> str:
    resolved = path.resolve()
    last_match = "unknown"
    for part in resolved.parts:
        if PCI_ADDR_PATTERN.fullmatch(part):
            last_match = part
    return last_match


def list_root_buses() -> list[UsbRootBus]:
    roots: list[UsbRootBus] = []
    for path in sorted(SYS_USB_ROOT.glob("usb*"), key=lambda p: int(p.name[3:])):
        if ":" in path.name:
            continue
        busnum_text = _read_text(path / "busnum")
        if not busnum_text:
            continue
        roots.append(
            UsbRootBus(
                bus_name=path.name,
                busnum=int(busnum_text),
                pci_controller=_pci_controller_for_path(path),
                usb_version=_read_text(path / "version"),
                root_speed_mbps=_read_text(path / "speed"),
                max_ports=_read_text(path / "maxchild"),
            )
        )
    return roots


def snapshot_devices() -> dict[str, UsbDevice]:
    roots = {root.busnum: root for root in list_root_buses()}
    devices: dict[str, UsbDevice] = {}
    for path in sorted(SYS_USB_ROOT.iterdir()):
        if ":" in path.name:
            continue
        if path.name.startswith("usb"):
            continue
        busnum_text = _read_text(path / "busnum")
        devnum_text = _read_text(path / "devnum")
        if not busnum_text or not devnum_text:
            continue
        devnum = int(devnum_text)
        if devnum == 1:
            continue
        busnum = int(busnum_text)
        root = roots.get(busnum)
        devices[path.name] = UsbDevice(
            sysfs_name=path.name,
            busnum=busnum,
            devnum=devnum,
            root_bus_name=root.bus_name if root else f"usb{busnum}",
            pci_controller=root.pci_controller if root else "unknown",
            speed_mbps=_read_text(path / "speed"),
            manufacturer=_read_text(path / "manufacturer"),
            product=_read_text(path / "product"),
            serial=_read_text(path / "serial"),
            vendor_id=_read_text(path / "idVendor"),
            product_id=_read_text(path / "idProduct"),
        )
    return devices


def _describe_device(device: UsbDevice) -> str:
    label = " ".join(part for part in [device.manufacturer, device.product] if part).strip() or "Unknown USB device"
    serial_part = f" serial={device.serial}" if device.serial else ""
    return (
        f"{label} [{device.vendor_id}:{device.product_id}]"
        f" bus={device.busnum}({device.root_bus_name})"
        f" controller={device.pci_controller}"
        f" speed={device.speed_mbps}M"
        f" sysfs={device.sysfs_name}"
        f"{serial_part}"
    )


def print_root_summary() -> None:
    print("USB root-bus to controller map")
    print("==============================")
    for root in list_root_buses():
        print(
            f"{root.bus_name}: bus={root.busnum} "
            f"controller={root.pci_controller} "
            f"usb={root.usb_version} "
            f"root_speed={root.root_speed_mbps}M "
            f"ports={root.max_ports}"
        )


def print_current_devices() -> None:
    devices = snapshot_devices()
    if not devices:
        print("No non-root USB devices detected.")
        return
    print("Current non-root USB devices")
    print("============================")
    for device in sorted(devices.values(), key=lambda item: (item.busnum, item.devnum, item.sysfs_name)):
        print(_describe_device(device))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Watch USB device add/remove events and print which USB bus/controller a device lands on. "
            "Useful for mapping physical ports to controllers before assigning cameras."
        )
    )
    parser.add_argument("--poll-s", type=float, default=1.0, help="Polling interval in seconds. Default: 1.0")
    parser.add_argument(
        "--no-list-current",
        action="store_true",
        help="Do not print the current non-root USB device list on startup.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.poll_s <= 0.0:
        raise ValueError("--poll-s must be greater than 0.")

    print_root_summary()
    print()
    if not args.no_list_current:
        print_current_devices()
        print()

    print("Watching for USB changes. Plug one device into one physical port at a time.")
    print("Press Ctrl+C to stop.")

    previous = snapshot_devices()
    try:
        while True:
            time.sleep(float(args.poll_s))
            current = snapshot_devices()
            added = sorted(set(current) - set(previous))
            removed = sorted(set(previous) - set(current))

            for sysfs_name in added:
                print(f"[ADDED]   {_describe_device(current[sysfs_name])}")
            for sysfs_name in removed:
                print(f"[REMOVED] {_describe_device(previous[sysfs_name])}")

            previous = current
    except KeyboardInterrupt:
        print("\nStopped USB watcher.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
