#!/usr/bin/env python3

"""Publish one or more RealSense devices into the V2 `/spark/cameras/...` contract."""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass

import pyrealsense2 as rs
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import Image


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class StreamProfile:
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class CameraSpec:
    attachment: str
    camera_slot: str
    serial_no: str
    color_profile: StreamProfile
    depth_profile: StreamProfile


def parse_profile(value: str) -> StreamProfile:
    tokens = [token.strip() for token in value.split(",")]
    if len(tokens) != 3:
        raise ValueError(f"Expected profile WIDTH,HEIGHT,FPS, got {value!r}")
    width, height, fps = (int(token) for token in tokens)
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError(f"Invalid non-positive profile component in {value!r}")
    return StreamProfile(width=width, height=height, fps=fps)


def parse_camera_spec(value: str) -> CameraSpec:
    tokens = [token.strip() for token in value.split(";", maxsplit=4)]
    if len(tokens) != 5:
        raise ValueError(
            "Expected camera spec ATTACHMENT;CAMERA_SLOT;SERIAL_NO;COLOR_PROFILE;DEPTH_PROFILE, "
            f"got {value!r}"
        )
    attachment, camera_slot, serial_no, color_profile, depth_profile = tokens
    if attachment not in {"lightning", "thunder", "world"}:
        raise ValueError(f"Camera spec has unsupported attachment {attachment!r}: {value!r}")
    if not camera_slot or "/" in camera_slot:
        raise ValueError(f"Camera spec has invalid camera slot {camera_slot!r}: {value!r}")
    if not normalize_serial(serial_no):
        raise ValueError(f"Camera spec is missing a serial number: {value!r}")
    return CameraSpec(
        attachment=attachment,
        camera_slot=camera_slot,
        serial_no=serial_no,
        color_profile=parse_profile(color_profile),
        depth_profile=parse_profile(depth_profile),
    )


def get_camera_info(device: rs.device, field: rs.camera_info) -> str:
    try:
        return device.get_info(field)
    except Exception:
        return ""


def normalize_serial(value: str) -> str:
    return value.strip().strip("'").strip('"').lower()


def serial_aliases(value: str) -> set[str]:
    normalized = normalize_serial(value)
    aliases = {normalized}
    trimmed = normalized.lstrip("0")
    if trimmed:
        aliases.add(trimmed)
    return aliases


def canonical_serial(value: str) -> str:
    aliases = sorted(serial_aliases(value), key=len)
    return aliases[0]


def intrinsics_payload(video_profile: rs.video_stream_profile, *, source: str) -> dict[str, object]:
    intr = video_profile.get_intrinsics()
    return {
        "camera_matrix": [
            [float(intr.fx), 0.0, float(intr.ppx)],
            [0.0, float(intr.fy), float(intr.ppy)],
            [0.0, 0.0, 1.0],
        ],
        "distortion_coeffs": [float(value) for value in intr.coeffs],
        "image_size": [int(intr.width), int(intr.height)],
        "distortion_model": str(intr.model),
        "source": source,
    }


def resolve_camera_specs(camera_specs: list[CameraSpec]) -> list[CameraSpec]:
    resolved_specs: list[CameraSpec] = []
    resolved_serials: set[str] = set()

    for spec in camera_specs:
        resolved_serial = canonical_serial(spec.serial_no)
        if resolved_serial in resolved_serials:
            raise RuntimeError(
                f"Multiple camera specs resolved to the same physical serial {resolved_serial!r}. "
                "Each launched camera must map to a unique device."
            )
        resolved_serials.add(resolved_serial)
        resolved_specs.append(
            CameraSpec(
                attachment=spec.attachment,
                camera_slot=spec.camera_slot,
                serial_no=resolved_serial,
                color_profile=spec.color_profile,
                depth_profile=spec.depth_profile,
            )
        )
    return resolved_specs


class RealSenseContractBridge(Node):
    def __init__(
        self,
        *,
        camera_slot: str,
        camera_namespace: str,
        serial_no: str,
        color_profile: StreamProfile,
        depth_profile: StreamProfile,
        enable_depth: bool,
        wait_for_frames_timeout_ms: int,
    ) -> None:
        super().__init__(camera_slot, namespace=camera_namespace)

        self.serial_no = serial_no
        self.camera_namespace = camera_namespace
        self.camera_slot = camera_slot
        self.color_profile = color_profile
        self.depth_profile = depth_profile
        self.enable_depth = enable_depth
        self.wait_for_frames_timeout_ms = wait_for_frames_timeout_ms
        self.frame_id = (
            "spark_"
            + camera_namespace.strip("/").replace("/", "_")
            + "_"
            + camera_slot
            + "_optical_frame"
        )
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._warned_missing_frame = False
        self._streaming_event = threading.Event()

        self._pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(self.serial_no)
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

        self._pipeline_profile = self._start_pipeline_with_retry(config)
        device = self._pipeline_profile.get_device()
        color_video_profile = self._pipeline_profile.get_stream(rs.stream.color).as_video_stream_profile()
        depth_video_profile = self._pipeline_profile.get_stream(rs.stream.depth).as_video_stream_profile()
        depth_scale_meters_per_unit = None
        try:
            depth_scale_meters_per_unit = float(device.first_depth_sensor().get_depth_scale())
        except Exception:
            depth_scale_meters_per_unit = None

        self.declare_parameter("serial_no", self.serial_no)
        self.declare_parameter("device_type", get_camera_info(device, rs.camera_info.name))
        self.declare_parameter("firmware_version", get_camera_info(device, rs.camera_info.firmware_version))
        self.declare_parameter("color_profile", self._format_profile(color_profile))
        self.declare_parameter("depth_profile", self._format_profile(depth_profile))
        self.declare_parameter(
            "color_intrinsics_json",
            json.dumps(
                intrinsics_payload(
                    color_video_profile,
                    source="realsense_sdk_factory_calibration",
                ),
                sort_keys=True,
            ),
        )
        self.declare_parameter(
            "depth_intrinsics_json",
            json.dumps(
                intrinsics_payload(
                    depth_video_profile,
                    source="realsense_sdk_factory_calibration",
                ),
                sort_keys=True,
            ),
        )
        if depth_scale_meters_per_unit is not None and depth_scale_meters_per_unit > 0.0:
            self.declare_parameter("depth_scale_meters_per_unit", depth_scale_meters_per_unit)
        self.declare_parameter("enable_depth", enable_depth)
        self.declare_parameter("wait_for_frames_timeout_ms", wait_for_frames_timeout_ms)

        self._color_pub = self.create_publisher(Image, "~/color/image_raw", 10)
        self._depth_pub = self.create_publisher(Image, "~/depth/image_rect_raw", 10)

        self.get_logger().info(
            "Initialized RealSense bridge for serial=%s model=%s color=%s depth=%s enable_depth=%s"
            % (
                self.serial_no,
                get_camera_info(device, rs.camera_info.name) or "<unknown>",
                self._format_profile(color_profile),
                self._format_profile(depth_profile),
                enable_depth,
            )
        )

    def start(self) -> None:
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def wait_until_streaming(self, timeout_s: float) -> bool:
        return self._streaming_event.wait(timeout=timeout_s)

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

    def _start_pipeline_with_retry(self, config: rs.config, *, max_attempts: int = 5, delay_s: float = 1.5):
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._pipeline.start(config)
            except RuntimeError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                self.get_logger().warning(
                    f"pipeline.start failed on attempt {attempt}/{max_attempts}: {exc}; retrying in {delay_s:.1f}s"
                )
                try:
                    self._pipeline.stop()
                except Exception:
                    pass
                time.sleep(delay_s)
        raise RuntimeError(f"Failed to start RealSense pipeline for serial={self.serial_no}: {last_error}")

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
                if not self._streaming_event.is_set():
                    self._streaming_event.set()
                    self.get_logger().info(
                        "Started RealSense bridge for serial=%s model=%s color=%s depth=%s enable_depth=%s"
                        % (
                            self.serial_no,
                            self.get_parameter("device_type").value or "<unknown>",
                            self._format_profile(self.color_profile),
                            self._format_profile(self.depth_profile),
                            self.enable_depth,
                        )
                    )
            except Exception:
                if not rclpy.ok() or self._stop_event.is_set():
                    break
                raise

    def _frame_to_image_msg(self, frame, stamp, encoding: str) -> Image:
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.height = frame.get_height()
        msg.width = frame.get_width()
        msg.encoding = encoding
        msg.is_bigendian = False
        msg.step = frame.get_stride_in_bytes()
        msg.data = bytes(frame.get_data())
        return msg


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-namespace", default="/spark/cameras")
    parser.add_argument("--enable-depth", default="true")
    parser.add_argument("--wait-for-frames-timeout-ms", type=int, default=5000)
    parser.add_argument("--startup-timeout-s", type=float, default=15.0)
    parser.add_argument(
        "--camera-spec",
        action="append",
        default=[],
        help=(
            "Repeatable multi-camera spec in the form "
            "ATTACHMENT;CAMERA_SLOT;SERIAL_NO;COLOR_PROFILE;DEPTH_PROFILE"
        ),
    )
    return parser


def build_camera_specs(args: argparse.Namespace) -> list[CameraSpec]:
    if args.camera_spec:
        return [parse_camera_spec(value) for value in args.camera_spec]
    raise ValueError("Provide at least one --camera-spec ATTACHMENT;CAMERA_SLOT;SERIAL_NO;COLOR_PROFILE;DEPTH_PROFILE.")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    enable_depth = parse_bool(args.enable_depth)
    camera_specs = resolve_camera_specs(build_camera_specs(args))

    rclpy.init(args=None)
    nodes: list[RealSenseContractBridge] = []
    executor = MultiThreadedExecutor(num_threads=max(2, len(camera_specs)))
    try:
        for spec in camera_specs:
            camera_namespace = f"{args.camera_namespace.rstrip('/')}/{spec.attachment}"
            node = RealSenseContractBridge(
                camera_slot=spec.camera_slot,
                camera_namespace=camera_namespace,
                serial_no=spec.serial_no,
                color_profile=spec.color_profile,
                depth_profile=spec.depth_profile,
                enable_depth=enable_depth,
                wait_for_frames_timeout_ms=args.wait_for_frames_timeout_ms,
            )
            node.start()
            if not node.wait_until_streaming(timeout_s=args.startup_timeout_s):
                raise RuntimeError(
                    f"Camera {spec.attachment}/{spec.camera_slot} (serial={node.serial_no}) did not produce frames within "
                    f"{args.startup_timeout_s:.1f}s."
                )
            nodes.append(node)
            executor.add_node(node)
    except Exception:
        for node in nodes:
            try:
                executor.remove_node(node)
            except Exception:
                pass
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        raise

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            try:
                executor.remove_node(node)
            except Exception:
                pass
            node.close()
            node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
