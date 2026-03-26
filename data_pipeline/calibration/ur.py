from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import rtde_control
import rtde_receive


REPO_ROOT = Path(__file__).resolve().parents[2]
TELEOP_ROOT = REPO_ROOT / "TeleopSoftware"
if str(TELEOP_ROOT) not in sys.path:
    sys.path.insert(0, str(TELEOP_ROOT))

from teleop_runtime_config import build_default_runtime_config  # type: ignore  # noqa: E402


_DISPLAY_TO_CANONICAL = {
    "Lightning": "lightning",
    "Thunder": "thunder",
}


@dataclass(frozen=True)
class ArmConnectionInfo:
    arm: str
    display_name: str
    ip_address: str


def load_arm_connection_info(active_arms: list[str] | tuple[str, ...] | None = None) -> dict[str, ArmConnectionInfo]:
    runtime_config = build_default_runtime_config()
    requested = {str(arm).strip().lower() for arm in (active_arms or []) if str(arm).strip()}
    info: dict[str, ArmConnectionInfo] = {}
    for arm_config in runtime_config.arms:
        canonical = _DISPLAY_TO_CANONICAL.get(arm_config.name)
        if canonical is None:
            continue
        if requested and canonical not in requested:
            continue
        info[canonical] = ArmConnectionInfo(
            arm=canonical,
            display_name=arm_config.name,
            ip_address=arm_config.ip_address,
        )
    return info


class CalibrationArm:
    def __init__(self, arm_info: ArmConnectionInfo, *, connect_control: bool = True):
        self.arm_info = arm_info
        self.state = rtde_receive.RTDEReceiveInterface(arm_info.ip_address)
        self.control = rtde_control.RTDEControlInterface(arm_info.ip_address, 500.0) if connect_control else None

    def get_actual_q(self) -> list[float]:
        return [float(value) for value in self.state.getActualQ()]

    def get_actual_tcp_pose(self) -> list[float]:
        return [float(value) for value in self.state.getActualTCPPose()]

    def enable_freedrive(self) -> None:
        if self.control is None:
            raise RuntimeError(f"Freedrive is unavailable for {self.arm_info.arm}: control interface not connected.")
        self.control.freedriveMode()

    def disable_freedrive(self) -> None:
        if self.control is not None:
            self.control.endFreedriveMode()

    def movej(self, joint_positions: list[float], speed: float = 0.6, acceleration: float = 0.8) -> None:
        if self.control is None:
            raise RuntimeError(f"moveJ is unavailable for {self.arm_info.arm}: control interface not connected.")
        self.control.moveJ(list(joint_positions), speed, acceleration)

    def close(self) -> None:
        try:
            self.disable_freedrive()
        except Exception:
            pass
        try:
            self.state.disconnect()
        except Exception:
            pass
        if self.control is not None:
            try:
                self.control.disconnect()
            except Exception:
                pass
