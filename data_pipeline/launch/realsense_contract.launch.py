import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, TimerAction
from launch.substitutions import LaunchConfiguration


REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
BRIDGE_SCRIPT = REPO_ROOT / "data_pipeline" / "realsense_bridge.py"
LOCAL_LIBREALSENSE_RELEASE = REPO_ROOT / "build" / "librealsense-v2.54.2" / "Release"


def _is_unset(value: str) -> bool:
    return value.strip() in {"", "''", '""'}


def _camera_process(context, camera_name: str, serial_key: str) -> ExecuteProcess:
    camera_namespace = "/" + LaunchConfiguration("camera_namespace").perform(context).strip("/")
    pythonpath = str(LOCAL_LIBREALSENSE_RELEASE)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath = f"{pythonpath}:{existing_pythonpath}"
    ld_library_path = str(LOCAL_LIBREALSENSE_RELEASE)
    existing_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
    if existing_ld_library_path:
        ld_library_path = f"{ld_library_path}:{existing_ld_library_path}"
    return ExecuteProcess(
        cmd=[
            str(VENV_PYTHON),
            str(BRIDGE_SCRIPT),
            "--camera-name",
            camera_name,
            "--camera-namespace",
            camera_namespace,
            "--serial-no",
            LaunchConfiguration(serial_key).perform(context).strip().strip("'").strip('"'),
            "--color-profile",
            LaunchConfiguration(f"{camera_name}_color_profile").perform(context),
            "--depth-profile",
            LaunchConfiguration(f"{camera_name}_depth_profile").perform(context),
            "--enable-depth",
            LaunchConfiguration("enable_depth").perform(context),
            "--wait-for-frames-timeout-ms",
            LaunchConfiguration("wait_for_frames_timeout_ms").perform(context),
        ],
        output="screen",
        emulate_tty=True,
        additional_env={
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": pythonpath,
            "LD_LIBRARY_PATH": ld_library_path,
        },
    )


def _launch_setup(context):
    wrist_serial = LaunchConfiguration("wrist_serial_no").perform(context)
    scene_serial = LaunchConfiguration("scene_serial_no").perform(context)
    actions = []
    stagger_sec = float(LaunchConfiguration("camera_start_stagger_sec").perform(context))
    wrist_enabled = not _is_unset(wrist_serial)
    scene_enabled = not _is_unset(scene_serial)

    if wrist_enabled:
        actions.append(_camera_process(context, "wrist", "wrist_serial_no"))
    if scene_enabled:
        scene_process = _camera_process(context, "scene", "scene_serial_no")
        if wrist_enabled and stagger_sec > 0.0:
            actions.append(TimerAction(period=stagger_sec, actions=[scene_process]))
        else:
            actions.append(scene_process)
    if not actions:
        raise RuntimeError("Provide at least one of wrist_serial_no or scene_serial_no.")
    return actions


def generate_launch_description() -> LaunchDescription:
    arguments = [
        DeclareLaunchArgument("camera_namespace", default_value="spark/cameras"),
        DeclareLaunchArgument("wrist_serial_no", default_value=""),
        DeclareLaunchArgument("scene_serial_no", default_value=""),
        DeclareLaunchArgument("wrist_color_profile", default_value="640,480,30"),
        DeclareLaunchArgument("scene_color_profile", default_value="640,480,30"),
        DeclareLaunchArgument("wrist_depth_profile", default_value="640,480,30"),
        DeclareLaunchArgument("scene_depth_profile", default_value="640,480,30"),
        DeclareLaunchArgument("enable_depth", default_value="true"),
        DeclareLaunchArgument("wait_for_frames_timeout_ms", default_value="5000"),
        DeclareLaunchArgument("camera_start_stagger_sec", default_value="2.0"),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
