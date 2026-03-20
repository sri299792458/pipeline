#!/usr/bin/env python3

"""Publish one RealSense device into the V1 `/spark/cameras/...` contract."""

from __future__ import annotations

import argparse
import threading
from dataclasses import dataclass

import pyrealsense2 as rs
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class StreamProfile:
    width: int
    height: int
    fps: int


def parse_profile(value: str) -> StreamProfile:
    tokens = [token.strip() for token in value.split(",")]
    if len(tokens) != 3:
        raise ValueError(f"Expected profile WIDTH,HEIGHT,FPS, got {value!r}")
    width, height, fps = (int(token) for token in tokens)
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError(f"Invalid non-positive profile component in {value!r}")
    return StreamProfile(width=width, height=height, fps=fps)


def get_camera_info(device: rs.device, field: rs.camera_info) -> str:
    try:
        return device.get_info(field)
    except Exception:
        return ""


class RealSenseContractBridge(Node):
    def __init__(
        self,
        *,
        camera_name: str,
        camera_namespace: str,
        serial_no: str,
        color_profile: StreamProfile,
        depth_profile: StreamProfile,
        enable_depth: bool,
        wait_for_frames_timeout_ms: int,
    ) -> None:
        super().__init__(camera_name, namespace=camera_namespace)

        self.serial_no = serial_no
        self.color_profile = color_profile
        self.depth_profile = depth_profile
        self.enable_depth = enable_depth
        self.wait_for_frames_timeout_ms = wait_for_frames_timeout_ms
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._warned_missing_frame = False

        self.declare_parameter("serial_no", serial_no)
        self.declare_parameter("device_type", "")
        self.declare_parameter("firmware_version", "")
        self.declare_parameter("color_profile", self._format_profile(color_profile))
        self.declare_parameter("depth_profile", self._format_profile(depth_profile))
        self.declare_parameter("enable_depth", enable_depth)
        self.declare_parameter("wait_for_frames_timeout_ms", wait_for_frames_timeout_ms)
        self._color_pub = self.create_publisher(Image, "~/color/image_raw", 10)
        self._depth_pub = self.create_publisher(Image, "~/depth/image_rect_raw", 10)

        self._pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(serial_no)
        config.enable_stream(
            rs.stream.color,
            color_profile.width,
            color_profile.height,
            rs.format.bgr8,
            color_profile.fps,
        )
        if enable_depth:
            config.enable_stream(
                rs.stream.depth,
                depth_profile.width,
                depth_profile.height,
                rs.format.z16,
                depth_profile.fps,
            )

        self._pipeline_profile = self._pipeline.start(config)
        device = self._pipeline_profile.get_device()
        self.set_parameters(
            [
                rclpy.parameter.Parameter(
                    "device_type",
                    rclpy.Parameter.Type.STRING,
                    get_camera_info(device, rs.camera_info.name),
                ),
                rclpy.parameter.Parameter(
                    "firmware_version",
                    rclpy.Parameter.Type.STRING,
                    get_camera_info(device, rs.camera_info.firmware_version),
                ),
            ]
        )

        self.get_logger().info(
            "Started RealSense bridge for serial=%s model=%s color=%s depth=%s enable_depth=%s"
            % (
                serial_no,
                get_camera_info(device, rs.camera_info.name) or "<unknown>",
                self._format_profile(color_profile),
                self._format_profile(depth_profile),
                enable_depth,
            )
        )

    def start(self) -> None:
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=2.0)
        try:
            self._pipeline.stop()
        except Exception:
            pass

    @staticmethod
    def _format_profile(profile: StreamProfile) -> str:
        return f"{profile.width},{profile.height},{profile.fps}"

    def _capture_loop(self) -> None:
        while rclpy.ok() and not self._stop_event.is_set():
            try:
                frames = self._pipeline.wait_for_frames(self.wait_for_frames_timeout_ms)
            except RuntimeError as exc:
                if not self._stop_event.is_set():
                    self.get_logger().warning(f"wait_for_frames failed: {exc}")
                continue

            stamp = self.get_clock().now().to_msg()
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame() if self.enable_depth else None

            if not color_frame or (self.enable_depth and not depth_frame):
                if not self._warned_missing_frame:
                    self.get_logger().warning("Received an incomplete frame batch; waiting for stable streams.")
                    self._warned_missing_frame = True
                continue

            self._warned_missing_frame = False
            try:
                self._color_pub.publish(self._frame_to_image_msg(color_frame, stamp, "bgr8"))
                if depth_frame is not None:
                    self._depth_pub.publish(self._frame_to_image_msg(depth_frame, stamp, "16UC1"))
            except Exception:
                if not rclpy.ok() or self._stop_event.is_set():
                    break
                raise

    def _frame_to_image_msg(self, frame, stamp, encoding: str) -> Image:
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = self.get_name()
        msg.height = frame.get_height()
        msg.width = frame.get_width()
        msg.encoding = encoding
        msg.is_bigendian = False
        msg.step = frame.get_stride_in_bytes()
        msg.data = bytes(frame.get_data())
        return msg


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-namespace", default="/spark/cameras")
    parser.add_argument("--serial-no", required=True)
    parser.add_argument("--color-profile", default="640,480,30")
    parser.add_argument("--depth-profile", default="640,480,30")
    parser.add_argument("--enable-depth", default="true")
    parser.add_argument("--wait-for-frames-timeout-ms", type=int, default=5000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    color_profile = parse_profile(args.color_profile)
    depth_profile = parse_profile(args.depth_profile)
    enable_depth = parse_bool(args.enable_depth)

    rclpy.init(args=None)
    node = RealSenseContractBridge(
        camera_name=args.camera_name,
        camera_namespace=args.camera_namespace,
        serial_no=args.serial_no,
        color_profile=color_profile,
        depth_profile=depth_profile,
        enable_depth=enable_depth,
        wait_for_frames_timeout_ms=args.wait_for_frames_timeout_ms,
    )
    node.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
