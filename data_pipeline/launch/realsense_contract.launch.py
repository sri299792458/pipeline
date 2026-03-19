from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _is_unset(value: str) -> bool:
    return value.strip() in {"", "''", '""'}


def _camera_node(context, camera_name: str, serial_key: str) -> Node:
    camera_namespace = LaunchConfiguration("camera_namespace").perform(context).strip("/")
    namespace = f"/{camera_namespace}"
    return Node(
        package="spark_realsense_bridge",
        executable="spark_realsense_bridge",
        namespace=namespace,
        name=camera_name,
        output="screen",
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
        remappings=[
            ("color/image_raw", f"{camera_name}/color/image_raw"),
            ("depth/image_rect_raw", f"{camera_name}/depth/image_rect_raw"),
        ],
        parameters=[
            {
                "camera_name": camera_name,
                "serial_no": LaunchConfiguration(serial_key),
                "rgb_camera.color_profile": LaunchConfiguration(f"{camera_name}_color_profile"),
                "depth_module.depth_profile": LaunchConfiguration(f"{camera_name}_depth_profile"),
                "enable_depth": LaunchConfiguration("enable_depth"),
                "initial_reset": LaunchConfiguration("initial_reset"),
            }
        ],
    )


def _launch_setup(context):
    wrist_serial = LaunchConfiguration("wrist_serial_no").perform(context)
    scene_serial = LaunchConfiguration("scene_serial_no").perform(context)
    if _is_unset(wrist_serial) or _is_unset(scene_serial):
        raise RuntimeError(
            "Both wrist_serial_no and scene_serial_no must be provided. "
            "The V1 manifest requires explicit RealSense serial numbers."
        )

    return [
        _camera_node(context, "wrist", "wrist_serial_no"),
        _camera_node(context, "scene", "scene_serial_no"),
    ]


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
        DeclareLaunchArgument("initial_reset", default_value="false"),
        DeclareLaunchArgument("log_level", default_value="info"),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
