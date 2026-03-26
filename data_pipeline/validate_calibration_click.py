#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pyrealsense2 as rs

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.calibration import CalibrationArm, pose6d_to_transform, load_arm_connection_info
from data_pipeline.pipeline_utils import (
    REPO_ROOT as PIPELINE_REPO_ROOT,
    camera_path_parts_for_role,
    load_optional_sensor_overrides,
)


DEFAULT_SENSORS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "sensors.local.yaml"
DEFAULT_RESULTS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "calibration.local.json"


def _load_transform_for_role(calibration_path: Path, role: str) -> dict:
    with calibration_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cameras = data.get("cameras", {})
    if role not in cameras:
        raise KeyError(f"Calibration for role {role} not found in {calibration_path}")
    return cameras[role]


def _depth_at(depth_m: np.ndarray, u: int, v: int) -> float | None:
    height, width = depth_m.shape
    if u < 0 or v < 0 or u >= width or v >= height:
        return None
    depth = float(depth_m[v, u])
    if depth > 0.0:
        return depth
    u0, u1 = max(0, u - 2), min(width, u + 3)
    v0, v1 = max(0, v - 2), min(height, v + 3)
    window = depth_m[v0:v1, u0:u1].reshape(-1)
    valid = window[window > 0.0]
    if valid.size == 0:
        return None
    return float(np.median(valid))


def _pixel_to_camera(u: int, v: int, depth_m: float, intrinsics) -> np.ndarray:
    x = (u - intrinsics.ppx) / intrinsics.fx * depth_m
    y = (v - intrinsics.ppy) / intrinsics.fy * depth_m
    z = depth_m
    return np.asarray([x, y, z], dtype=np.float64)


def _world_from_camera_transform(role: str, calibration_entry: dict, arm_handle: CalibrationArm | None) -> np.ndarray:
    camera_parts = camera_path_parts_for_role(role)
    if camera_parts is None:
        raise ValueError(f"Role {role} is not a camera role.")
    attachment, mount_site = camera_parts
    if mount_site.startswith("scene_"):
        extrinsics = calibration_entry.get("extrinsics", {})
        transform = np.eye(4, dtype=np.float64)
        transform[:3, :3] = np.asarray(extrinsics["rotation_matrix"], dtype=np.float64)
        transform[:3, 3] = np.asarray(extrinsics["translation_vector"], dtype=np.float64)
        return transform

    if arm_handle is None:
        raise RuntimeError(f"Wrist camera {role} requires a live robot connection.")
    hand_eye = calibration_entry.get("hand_eye_calibration", {})
    flange_from_camera = np.eye(4, dtype=np.float64)
    flange_from_camera[:3, :3] = np.asarray(hand_eye["rotation_matrix"], dtype=np.float64)
    flange_from_camera[:3, 3] = np.asarray(hand_eye["translation_vector"], dtype=np.float64)
    base_from_flange = pose6d_to_transform(arm_handle.get_actual_tcp_pose())
    return base_from_flange @ flange_from_camera


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Click a RealSense pixel and inspect its calibrated 3D point.")
    parser.add_argument("--camera-role", required=True)
    parser.add_argument("--sensors-file", default=str(DEFAULT_SENSORS_FILE))
    parser.add_argument("--calibration-file", default=str(DEFAULT_RESULTS_FILE))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    sensor_overrides = load_optional_sensor_overrides(args.sensors_file)
    sensor = sensor_overrides.get(args.camera_role)
    if not isinstance(sensor, dict):
        raise KeyError(f"Camera role {args.camera_role} not found in {args.sensors_file}")
    serial_number = str(sensor.get("serial_number", "")).strip()
    if not serial_number:
        raise RuntimeError(f"Camera role {args.camera_role} is missing serial_number in {args.sensors_file}")

    calibration_entry = _load_transform_for_role(Path(args.calibration_file).expanduser(), args.camera_role)
    attachment, mount_site = camera_path_parts_for_role(args.camera_role) or ("world", args.camera_role)
    arm_handle = None
    if mount_site.startswith("wrist_"):
        arm_info = load_arm_connection_info([attachment])
        arm_handle = CalibrationArm(arm_info[attachment], connect_control=False)

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial_number)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    profile = pipeline.start(config)
    align = rs.align(rs.stream.color)
    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
    intrinsics = color_profile.get_intrinsics()
    last_depth_m: np.ndarray | None = None

    window_name = f"click-{args.camera_role}"

    def on_mouse(event, x, y, flags, param):
        del flags, param
        nonlocal last_depth_m
        if event != cv2.EVENT_LBUTTONDOWN or last_depth_m is None:
            return
        depth_m = _depth_at(last_depth_m, x, y)
        if depth_m is None:
            print(f"Pixel ({x}, {y}): no valid depth")
            return
        point_camera = _pixel_to_camera(x, y, depth_m, intrinsics)
        world_from_camera = _world_from_camera_transform(args.camera_role, calibration_entry, arm_handle)
        point_world = (world_from_camera[:3, :3] @ point_camera) + world_from_camera[:3, 3]
        print(f"Pixel ({x}, {y}) depth={depth_m:.4f} m")
        print(f"Camera point: [{point_camera[0]:.4f}, {point_camera[1]:.4f}, {point_camera[2]:.4f}]")
        print(f"Calibrated point: [{point_world[0]:.4f}, {point_world[1]:.4f}, {point_world[2]:.4f}]")
        if arm_handle is not None:
            tcp_pose = arm_handle.get_actual_tcp_pose()
            print(
                "Actual TCP pose: "
                f"[{tcp_pose[0]:.4f}, {tcp_pose[1]:.4f}, {tcp_pose[2]:.4f}, "
                f"{tcp_pose[3]:.4f}, {tcp_pose[4]:.4f}, {tcp_pose[5]:.4f}]"
            )

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, on_mouse)
    try:
        while True:
            frames = align.process(pipeline.wait_for_frames())
            depth_frame = frames.get_depth_frame()
            color_frame = frames.get_color_frame()
            if not depth_frame or not color_frame:
                continue
            last_depth_m = np.asanyarray(depth_frame.get_data()).astype(np.float32) * float(depth_scale)
            color = np.asanyarray(color_frame.get_data())
            cv2.imshow(window_name, color)
            key = cv2.waitKey(1) & 0xFF
            if key in {27, ord("q")}:
                break
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
        if arm_handle is not None:
            arm_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
