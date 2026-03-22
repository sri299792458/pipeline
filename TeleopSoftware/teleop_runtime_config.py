from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArmRuntimeConfig:
    name: str
    ip_address: str
    enable_control: bool
    enable_gripper: bool
    home_joints_rad: tuple[float, ...]
    spark_home_joints_rad: tuple[float, ...] | None = None


@dataclass(frozen=True)
class TeleopRuntimeConfig:
    arms: tuple[ArmRuntimeConfig, ...]

    def arm_names(self) -> list[str]:
        return [arm.name for arm in self.arms]

    def arm_ips(self) -> list[str]:
        return [arm.ip_address for arm in self.arms]

    def enable_control_map(self) -> dict[str, bool]:
        return {arm.name: arm.enable_control for arm in self.arms}

    def enable_gripper_map(self) -> dict[str, bool]:
        return {arm.name: arm.enable_gripper for arm in self.arms}

    def homes_map(self) -> dict[str, list[float]]:
        homes: dict[str, list[float]] = {}
        for arm in self.arms:
            homes[arm.name] = [float(angle) for angle in arm.home_joints_rad]
            spark_home = arm.spark_home_joints_rad or arm.home_joints_rad
            homes[f"{arm.name}_spark"] = [float(angle) for angle in spark_home]
        return homes


def build_default_runtime_config() -> TeleopRuntimeConfig:
    return TeleopRuntimeConfig(
        arms=(
            ArmRuntimeConfig(
                name="Lightning",
                ip_address="10.33.55.90",
                enable_control=True,
                enable_gripper=True,
                home_joints_rad=(
                    -3.092430591583252,
                    -2.535433530807495,
                    -1.2771631479263306,
                    -1.0458279848098755,
                    -0.0320628322660923,
                    -0.025522056967020035,
                ),
            ),
            ArmRuntimeConfig(
                name="Thunder",
                ip_address="10.33.55.89",
                enable_control=True,
                enable_gripper=True,
                home_joints_rad=(
                    3.181920289993286,
                    -0.16607506573200226,
                    0.2841489911079407,
                    -1.0576382875442505,
                    -0.10265476256608963,
                    -0.7487161755561829,
                ),
            ),
        ),
    )
