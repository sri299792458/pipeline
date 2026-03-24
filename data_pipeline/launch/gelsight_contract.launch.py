from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_SCRIPT = REPO_ROOT / "data_pipeline" / "gelsight_bridge.py"


def _is_unset(value: str) -> bool:
    return value.strip() in {"", "''", '""'}


def _launch_setup(context):
    sensor_specs = LaunchConfiguration("sensor_specs").perform(context).strip()
    if _is_unset(sensor_specs):
        raise RuntimeError("Provide sensor_specs in the form ARM;FINGER_SLOT;DEVICE_PATH.")

    processes = []
    for spec in (item.strip() for item in sensor_specs.split("|")):
        if not spec:
            continue
        arm, finger_slot, device_path = [token.strip() for token in spec.split(";", maxsplit=2)]
        processes.append(
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    str(BRIDGE_SCRIPT),
                    "--arm",
                    arm,
                    "--finger-slot",
                    finger_slot,
                    "--device-path",
                    device_path,
                    "--width",
                    LaunchConfiguration("width"),
                    "--height",
                    LaunchConfiguration("height"),
                    "--border-fraction",
                    LaunchConfiguration("border_fraction"),
                    "--fps",
                    LaunchConfiguration("fps"),
                    "--frame-id",
                    f"spark_tactile_{arm}_{finger_slot}_optical_frame",
                ],
                output="screen",
            )
        )
    return processes


def generate_launch_description() -> LaunchDescription:
    arguments = [
        DeclareLaunchArgument("sensor_specs", default_value=""),
        DeclareLaunchArgument("width", default_value="320"),
        DeclareLaunchArgument("height", default_value="240"),
        DeclareLaunchArgument("border_fraction", default_value="0.15"),
        DeclareLaunchArgument("fps", default_value="20.0"),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
