import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration


REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PYTHON = Path("/usr/bin/python3")
BRIDGE_SCRIPT = REPO_ROOT / "data_pipeline" / "realsense_bridge.py"
LOCAL_LIBREALSENSE_RELEASE = REPO_ROOT / "build" / "librealsense-v2.54.2" / "Release"


def _is_unset(value: str) -> bool:
    return value.strip() in {"", "''", '""'}


def _append_camera_spec(cmd: list[str], spec: str) -> None:
    cmd.extend(["--camera-spec", spec])


def _launch_setup(context):
    camera_specs = LaunchConfiguration("camera_specs").perform(context).strip()

    if _is_unset(camera_specs):
        raise RuntimeError("Provide camera_specs in the form ATTACHMENT;CAMERA_SLOT;SERIAL_NO;COLOR_PROFILE;DEPTH_PROFILE.")

    pythonpath = str(LOCAL_LIBREALSENSE_RELEASE)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath = f"{pythonpath}:{existing_pythonpath}"

    ld_library_path = str(LOCAL_LIBREALSENSE_RELEASE)
    existing_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
    if existing_ld_library_path:
        ld_library_path = f"{ld_library_path}:{existing_ld_library_path}"

    cmd = [
        str(SYSTEM_PYTHON),
        str(BRIDGE_SCRIPT),
        "--camera-namespace",
        "/" + LaunchConfiguration("camera_namespace").perform(context).strip("/"),
        "--enable-depth",
        LaunchConfiguration("enable_depth").perform(context),
        "--wait-for-frames-timeout-ms",
        LaunchConfiguration("wait_for_frames_timeout_ms").perform(context),
        "--startup-timeout-s",
        LaunchConfiguration("startup_timeout_s").perform(context),
    ]

    for spec in (item.strip() for item in camera_specs.split("|")):
        if not spec:
            continue
        _append_camera_spec(cmd, spec)

    return [
        ExecuteProcess(
            cmd=cmd,
            output="screen",
            emulate_tty=True,
            additional_env={
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": pythonpath,
                "LD_LIBRARY_PATH": ld_library_path,
            },
        )
    ]


def generate_launch_description() -> LaunchDescription:
    arguments = [
        DeclareLaunchArgument("camera_namespace", default_value="spark/cameras"),
        DeclareLaunchArgument("camera_specs", default_value=""),
        DeclareLaunchArgument("enable_depth", default_value="true"),
        DeclareLaunchArgument("wait_for_frames_timeout_ms", default_value="5000"),
        DeclareLaunchArgument("startup_timeout_s", default_value="15.0"),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
