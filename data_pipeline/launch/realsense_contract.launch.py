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


def _append_camera_spec(cmd: list[str], *, camera_name: str, serial_no: str, color_profile: str, depth_profile: str) -> None:
    cmd.extend(
        [
            "--camera-spec",
            f"{camera_name};{serial_no};{color_profile};{depth_profile}",
        ]
    )


def _launch_setup(context):
    wrist_serial = LaunchConfiguration("wrist_serial_no").perform(context).strip().strip("'").strip('"')
    scene_serial = LaunchConfiguration("scene_serial_no").perform(context).strip().strip("'").strip('"')
    extra_specs = LaunchConfiguration("extra_camera_specs").perform(context).strip()

    if _is_unset(wrist_serial) and _is_unset(scene_serial) and _is_unset(extra_specs):
        raise RuntimeError("Provide at least one of wrist_serial_no, scene_serial_no, or extra_camera_specs.")

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

    if not _is_unset(wrist_serial):
        _append_camera_spec(
            cmd,
            camera_name="wrist",
            serial_no=wrist_serial,
            color_profile=LaunchConfiguration("wrist_color_profile").perform(context),
            depth_profile=LaunchConfiguration("wrist_depth_profile").perform(context),
        )
    if not _is_unset(scene_serial):
        _append_camera_spec(
            cmd,
            camera_name="scene",
            serial_no=scene_serial,
            color_profile=LaunchConfiguration("scene_color_profile").perform(context),
            depth_profile=LaunchConfiguration("scene_depth_profile").perform(context),
        )
    if not _is_unset(extra_specs):
        for spec in (item.strip() for item in extra_specs.split("|")):
            if not spec:
                continue
            cmd.extend(["--camera-spec", spec])

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
        DeclareLaunchArgument("wrist_serial_no", default_value=""),
        DeclareLaunchArgument("scene_serial_no", default_value=""),
        DeclareLaunchArgument("extra_camera_specs", default_value=""),
        DeclareLaunchArgument("wrist_color_profile", default_value="640,480,30"),
        DeclareLaunchArgument("scene_color_profile", default_value="640,480,30"),
        DeclareLaunchArgument("wrist_depth_profile", default_value="640,480,30"),
        DeclareLaunchArgument("scene_depth_profile", default_value="640,480,30"),
        DeclareLaunchArgument("enable_depth", default_value="true"),
        DeclareLaunchArgument("wait_for_frames_timeout_ms", default_value="5000"),
        DeclareLaunchArgument("startup_timeout_s", default_value="15.0"),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
