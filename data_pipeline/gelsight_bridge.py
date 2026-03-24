#!/usr/bin/python3

"""Publish GelSight Mini frames onto the V2 tactile ROS 2 topic contract."""

from __future__ import annotations

import argparse
import glob
import platform
import sys
from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
GSROBOTICS_ROOT = REPO_ROOT / "gsrobotics"

if str(GSROBOTICS_ROOT) not in sys.path:
    sys.path.insert(0, str(GSROBOTICS_ROOT))

from utilities.image_processing import crop_and_resize  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=["lightning", "thunder"], required=True)
    parser.add_argument("--finger-slot", choices=["finger_left", "finger_right"], required=True)
    parser.add_argument("--device-path", default="")
    parser.add_argument("--device-index", type=int, default=-1)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--border-fraction", type=float, default=0.15)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--frame-id", default="")
    return parser


class GelSightBridge(Node):
    """Publish tactile RGB frames with host-capture timestamps."""

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(f"gelsight_{args.arm}_{args.finger_slot}_bridge")
        self.args = args
        self.bridge = CvBridge()
        self.topic_name = f"/spark/tactile/{args.arm}/{args.finger_slot}/color/image_raw"
        self.publisher = self.create_publisher(
            Image,
            self.topic_name,
            10,
        )
        self.device = self._resolve_device(args)
        self.camera = cv2.VideoCapture(self.device)
        if not self.camera.isOpened():
            raise RuntimeError(f"Could not open GelSight device: {self.device}")
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        capture_width = int(round(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)))
        capture_height = int(round(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        frame_id = args.frame_id or f"spark_tactile_{args.arm}_{args.finger_slot}_optical_frame"
        self.frame_id = frame_id
        self.declare_parameter("device_path", args.device_path)
        self.declare_parameter("device_index", int(args.device_index))
        self.declare_parameter("capture_width", capture_width)
        self.declare_parameter("capture_height", capture_height)
        self.declare_parameter("output_width", int(args.width))
        self.declare_parameter("output_height", int(args.height))
        self.declare_parameter("border_fraction", float(args.border_fraction))
        self.declare_parameter("fps", float(args.fps))
        self.declare_parameter("frame_id", self.frame_id)
        self.declare_parameter("encoding", "rgb8")
        self.declare_parameter("preprocessing_pipeline", "crop_and_resize")
        self.declare_parameter("crop_applied", bool(args.border_fraction > 0.0))
        self.timer = self.create_timer(1.0 / args.fps, self._publish_frame)
        self._consecutive_errors = 0

        self.get_logger().info(
            "Publishing GelSight frames on %s from %s at %.2f Hz"
            % (
                self.topic_name,
                self.device,
                args.fps,
            )
        )

    def _resolve_device(self, args: argparse.Namespace) -> str | int:
        if args.device_path:
            return args.device_path
        if args.device_index >= 0:
            return args.device_index
        available_devices = self._list_devices()
        raise ValueError(
            "A GelSight device must be selected with --device-path or --device-index. "
            f"Detected devices: {available_devices}"
        )

    def _list_devices(self) -> dict[int, str]:
        if platform.system() == "Linux":
            return {idx: path for idx, path in enumerate(glob.glob("/dev/v4l/by-id/*"))}

        devices: dict[int, str] = {}
        for idx in range(6):
            capture = cv2.VideoCapture(idx)
            if capture.isOpened():
                devices[idx] = f"Camera {idx}"
                capture.release()
        return devices

    def _publish_frame(self) -> None:
        try:
            ok, bgr_frame = self.camera.read()
            stamp = self.get_clock().now().to_msg()
            if not ok:
                raise RuntimeError("Failed to read frame from device.")
        except Exception as exc:  # pragma: no cover - hardware path
            self._consecutive_errors += 1
            if self._consecutive_errors == 1 or self._consecutive_errors % 20 == 0:
                self.get_logger().warning(f"Failed to read GelSight frame: {exc}")
            return

        self._consecutive_errors = 0
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        rgb_frame = crop_and_resize(
            image=rgb_frame,
            target_size=(self.args.width, self.args.height),
            border_fraction=self.args.border_fraction,
        )

        msg = self.bridge.cv2_to_imgmsg(rgb_frame, encoding="rgb8")
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        self.publisher.publish(msg)

    def destroy_node(self) -> bool:
        try:
            self.camera.release()
        finally:
            return super().destroy_node()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    parser = build_arg_parser()
    args = parser.parse_args(remove_ros_args(args=argv)[1:])
    rclpy.init(args=argv)
    node = GelSightBridge(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
