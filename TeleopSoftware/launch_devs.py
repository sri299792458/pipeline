from __future__ import annotations

import argparse
import atexit

import rclpy
from rclpy.node import Node

from teleop_device_launcher import TeleopDeviceLaunchConfig, TeleopDeviceLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch SPARK device nodes and optional legacy USB peripherals.",
    )
    parser.add_argument(
        "--spark-device",
        action="append",
        default=[],
        help="Explicit SPARK serial device path. May be passed multiple times. If omitted, cp210x devices are auto-discovered.",
    )
    parser.add_argument(
        "--buffered-spark-topic",
        action="store_true",
        help="Publish SPARK angles on Spark_angle_buffer/<arm> instead of Spark_angle/<arm>.",
    )
    parser.add_argument(
        "--no-space-mouse",
        action="store_true",
        help="Skip legacy SpaceMouse auto-launch.",
    )
    parser.add_argument(
        "--no-vr",
        action="store_true",
        help="Skip legacy VR auto-launch.",
    )
    parser.add_argument(
        "--startup-settle-s",
        type=float,
        default=8.0,
        help="Seconds to wait after spawning child processes before reporting startup complete.",
    )
    return parser.parse_args()


class LaunchDevs(Node):
    def __init__(self, config: TeleopDeviceLaunchConfig):
        super().__init__("LaunchDevs")
        self.get_logger().info("Starting LaunchDevs")
        self.launcher = TeleopDeviceLauncher(config)
        self.modules: list = []

    def cleanup(self) -> None:
        TeleopDeviceLauncher.stop_all(self.modules)
        print("Exiting")

    def main(self) -> None:
        print("Starting modules---------------------")
        self.modules = self.launcher.start_all()
        print("Modules started----------------------")
        atexit.register(self.cleanup)
        rclpy.spin(self)


def build_launch_config(args: argparse.Namespace) -> TeleopDeviceLaunchConfig:
    return TeleopDeviceLaunchConfig(
        spark_devices=tuple(args.spark_device),
        include_space_mouse=not args.no_space_mouse,
        include_vr=not args.no_vr,
        buffered_spark_topic=bool(args.buffered_spark_topic),
        startup_settle_s=float(args.startup_settle_s),
    )


if __name__ == "__main__":
    args = parse_args()
    rclpy.init()
    node = LaunchDevs(build_launch_config(args))
    node.main()
    node.destroy_node()
    rclpy.shutdown()
