from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import time


@dataclass(frozen=True)
class DeviceCandidate:
    kind: str
    device_path: str
    descriptor: str


@dataclass(frozen=True)
class TeleopDeviceLaunchConfig:
    spark_devices: tuple[str, ...] = ()
    include_space_mouse: bool = True
    include_vr: bool = True
    buffered_spark_topic: bool = False
    startup_settle_s: float = 8.0
    python_executable: str = sys.executable
    teleop_root: Path = Path(__file__).resolve().parent

    @property
    def spark_node_path(self) -> Path:
        return self.teleop_root / "Spark" / "SparkNode.py"

    @property
    def space_mouse_node_path(self) -> Path:
        return self.teleop_root / "SM" / "SpaceMouseROS.py"

    @property
    def vr_node_path(self) -> Path:
        return self.teleop_root / "VR" / "VR_Node.py"


class TeleopDeviceDiscovery:
    SERIAL_PREFIXES = ("ttyUSB", "ttyACM")

    def _udevadm_info(self, device_path: str) -> str:
        try:
            result = subprocess.run(
                ["udevadm", "info", "--name", device_path, "--attribute-walk"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
        return result.stdout

    def discover_spark_devices(self) -> list[DeviceCandidate]:
        candidates: list[DeviceCandidate] = []
        seen_real_paths: set[str] = set()

        for entry in sorted(os.listdir("/dev")):
            if not entry.startswith(self.SERIAL_PREFIXES):
                continue
            device_path = f"/dev/{entry}"
            udev_info = self._udevadm_info(device_path)
            if not any(marker in udev_info for marker in ("cp210x", "Silicon Labs", "CP210")):
                continue
            real_path = os.path.realpath(device_path)
            if real_path in seen_real_paths:
                continue
            seen_real_paths.add(real_path)
            descriptor = "cp210x"
            if "Silicon Labs" in udev_info:
                descriptor = "Silicon Labs CP210x"
            candidates.append(
                DeviceCandidate(
                    kind="spark",
                    device_path=device_path,
                    descriptor=descriptor,
                )
            )
        return candidates

    def discover_space_mouse_devices(self) -> list[DeviceCandidate]:
        candidates: list[DeviceCandidate] = []
        for entry in sorted(os.listdir("/dev")):
            if not entry.startswith("hidraw"):
                continue
            device_path = f"/dev/{entry}"
            udev_info = self._udevadm_info(device_path)
            if "3Dconnexion" not in udev_info:
                continue
            candidates.append(
                DeviceCandidate(
                    kind="space_mouse",
                    device_path=device_path,
                    descriptor="3Dconnexion",
                )
            )
        return candidates

    def discover_vr_devices(self) -> list[DeviceCandidate]:
        device_path = "/dev/serial/by-id/usb-HTC_Hub_Controller-if00"
        if os.path.exists(device_path):
            return [DeviceCandidate(kind="vr", device_path=device_path, descriptor="HTC Hub Controller")]
        return []


class TeleopDeviceLauncher:
    def __init__(self, config: TeleopDeviceLaunchConfig):
        self.config = config
        self.discovery = TeleopDeviceDiscovery()

    def resolve_spark_devices(self) -> list[DeviceCandidate]:
        if self.config.spark_devices:
            return [
                DeviceCandidate(kind="spark", device_path=device_path, descriptor="explicit")
                for device_path in self.config.spark_devices
            ]
        return self.discovery.discover_spark_devices()

    def _build_spark_command(self, device_path: str) -> list[str]:
        command = [
            self.config.python_executable,
            str(self.config.spark_node_path),
            device_path,
        ]
        if self.config.buffered_spark_topic:
            command.append("--buffered-topic")
        return command

    def _build_space_mouse_command(self, device_path: str) -> list[str]:
        return [
            self.config.python_executable,
            str(self.config.space_mouse_node_path),
            device_path,
        ]

    def _build_vr_command(self) -> list[str]:
        return [
            self.config.python_executable,
            str(self.config.vr_node_path),
        ]

    def start_all(self) -> list[subprocess.Popen[bytes]]:
        modules: list[subprocess.Popen[bytes]] = []

        spark_devices = self.resolve_spark_devices()
        for candidate in spark_devices:
            print(f"Spark Device found: {candidate.device_path} ({candidate.descriptor})")
            modules.append(subprocess.Popen(self._build_spark_command(candidate.device_path), start_new_session=True))

        if self.config.include_space_mouse:
            for candidate in self.discovery.discover_space_mouse_devices():
                print(f"SpaceMouse Device found: {candidate.device_path}")
                modules.append(
                    subprocess.Popen(self._build_space_mouse_command(candidate.device_path), start_new_session=True)
                )

        if self.config.include_vr:
            for candidate in self.discovery.discover_vr_devices():
                print(f"VR Device found: {candidate.device_path}")
                modules.append(subprocess.Popen(self._build_vr_command(), start_new_session=True))

        if self.config.startup_settle_s > 0:
            time.sleep(self.config.startup_settle_s)
        return modules

    @staticmethod
    def stop_all(modules: list[subprocess.Popen[bytes]]) -> None:
        for module in modules:
            if module.poll() is None:
                module.kill()

