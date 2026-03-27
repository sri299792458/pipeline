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
DEFAULT_TIP_OFFSET_M = np.asarray([0.0, 0.0, 0.162], dtype=np.float64)
HOME_MOVE_SPEED_RAD_S = 0.6
HOME_MOVE_ACCEL_RAD_S2 = 0.8


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


def _pose6d_from_transform(transform: np.ndarray) -> list[float]:
    transform = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    rotvec, _ = cv2.Rodrigues(transform[:3, :3])
    return [
        float(transform[0, 3]),
        float(transform[1, 3]),
        float(transform[2, 3]),
        float(rotvec[0, 0]),
        float(rotvec[1, 0]),
        float(rotvec[2, 0]),
    ]


def _offset_transform(offset_m: np.ndarray) -> np.ndarray:
    transform = np.eye(4, dtype=np.float64)
    transform[:3, 3] = np.asarray(offset_m, dtype=np.float64).reshape(3)
    return transform


def _reference_from_camera_transform(
    role: str,
    calibration_entry: dict,
    arm_handle: CalibrationArm | None,
) -> tuple[np.ndarray, str]:
    camera_parts = camera_path_parts_for_role(role)
    if camera_parts is None:
        raise ValueError(f"Role {role} is not a camera role.")
    attachment, mount_site = camera_parts
    if mount_site.startswith("scene_"):
        extrinsics = calibration_entry.get("extrinsics", {})
        transform = np.eye(4, dtype=np.float64)
        transform[:3, :3] = np.asarray(extrinsics["rotation_matrix"], dtype=np.float64)
        transform[:3, 3] = np.asarray(extrinsics["translation_vector"], dtype=np.float64)
        return transform, str(extrinsics.get("reference_frame", "reference"))

    if arm_handle is None:
        raise RuntimeError(f"Wrist camera {role} requires a live robot connection.")
    hand_eye = calibration_entry.get("hand_eye_calibration", {})
    flange_from_camera = np.eye(4, dtype=np.float64)
    flange_from_camera[:3, :3] = np.asarray(hand_eye["rotation_matrix"], dtype=np.float64)
    flange_from_camera[:3, 3] = np.asarray(hand_eye["translation_vector"], dtype=np.float64)
    base_from_flange = pose6d_to_transform(arm_handle.get_actual_tcp_pose())
    return base_from_flange @ flange_from_camera, f"{attachment}_base"


def _validation_arm_for_role(role: str, calibration_entry: dict) -> str:
    camera_parts = camera_path_parts_for_role(role)
    if camera_parts is None:
        raise ValueError(f"Role {role} is not a camera role.")
    attachment, mount_site = camera_parts
    if mount_site.startswith("wrist_"):
        return attachment
    extrinsics = calibration_entry.get("extrinsics", {})
    reference_frame = str(extrinsics.get("reference_frame", "")).strip()
    if reference_frame.endswith("_base"):
        arm = reference_frame[: -len("_base")]
        if arm:
            return arm
    raise RuntimeError(f"Could not determine validation arm for role {role}.")


def _current_tip_transform(tcp_pose: list[float], tip_offset_m: np.ndarray) -> np.ndarray:
    transform = pose6d_to_transform(tcp_pose)
    return transform @ _offset_transform(tip_offset_m)


def _target_tcp_pose_for_point(
    current_tcp_pose: list[float],
    target_point_reference: np.ndarray,
    tip_offset_m: np.ndarray,
) -> list[float]:
    current_tip = _current_tip_transform(current_tcp_pose, tip_offset_m)
    target_tip = np.eye(4, dtype=np.float64)
    target_tip[:3, :3] = current_tip[:3, :3]
    target_tip[:3, 3] = np.asarray(target_point_reference, dtype=np.float64).reshape(3)
    target_flange = target_tip @ np.linalg.inv(_offset_transform(tip_offset_m))
    return _pose6d_from_transform(target_flange)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Click a calibrated pixel, print its reference-frame point, and optionally move the tool tip there with confirmation."
    )
    parser.add_argument("--camera-role", required=True)
    parser.add_argument("--sensors-file", default=str(DEFAULT_SENSORS_FILE))
    parser.add_argument("--calibration-file", default=str(DEFAULT_RESULTS_FILE))
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--move-speed", type=float, default=0.03, help="moveL speed in m/s.")
    parser.add_argument("--move-acceleration", type=float, default=0.08, help="moveL acceleration in m/s^2.")
    parser.add_argument(
        "--tcp-offset-m",
        type=float,
        nargs=3,
        default=tuple(float(v) for v in DEFAULT_TIP_OFFSET_M.tolist()),
        metavar=("X", "Y", "Z"),
        help="Tool-tip offset from flange in meters. Defaults to 0 0 0.162.",
    )
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
    validation_arm = _validation_arm_for_role(args.camera_role, calibration_entry)
    arm_info = load_arm_connection_info([validation_arm])
    if validation_arm not in arm_info:
        raise RuntimeError(f"Missing runtime connection info for validation arm {validation_arm}.")
    arm_handle = CalibrationArm(arm_info[validation_arm], connect_control=True)
    tip_offset_m = np.asarray(args.tcp_offset_m, dtype=np.float64).reshape(3)
    print(f"Using tip offset from flange: {tip_offset_m.tolist()}")

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

    window_name = f"click-{args.camera_role}"
    last_depth_m: np.ndarray | None = None
    should_exit = False
    def move_to_point(reference_point: np.ndarray) -> None:
        nonlocal should_exit
        target_reference_point = np.asarray(reference_point, dtype=np.float64).reshape(3)
        confirm = input(f"Move {validation_arm} tip to {target_reference_point.round(4).tolist()}? [y/N] ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Move canceled.")
            return
        print(f"Moving {validation_arm} to home before validation move...")
        arm_handle.movej(
            list(arm_info[validation_arm].home_joints_rad),
            speed=HOME_MOVE_SPEED_RAD_S,
            acceleration=HOME_MOVE_ACCEL_RAD_S2,
        )
        home_tcp_pose = arm_handle.get_actual_tcp_pose()
        target_tcp_pose = _target_tcp_pose_for_point(home_tcp_pose, target_reference_point, tip_offset_m)
        arm_handle.movel(target_tcp_pose, speed=float(args.move_speed), acceleration=float(args.move_acceleration))

        reached_tcp_pose = arm_handle.get_actual_tcp_pose()
        reached_tip = _current_tip_transform(reached_tcp_pose, tip_offset_m)
        reached_position = reached_tip[:3, 3]
        reached_delta = reached_position - target_reference_point
        print(
            f"Reached tip point: "
            f"[{reached_position[0]:.4f}, {reached_position[1]:.4f}, {reached_position[2]:.4f}]"
        )
        print(
            f"Reached delta (tip - target): "
            f"[{reached_delta[0]:.4f}, {reached_delta[1]:.4f}, {reached_delta[2]:.4f}]"
        )
        should_exit = True

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
        reference_from_camera, reference_frame = _reference_from_camera_transform(
            args.camera_role,
            calibration_entry,
            arm_handle,
        )
        point_reference = (reference_from_camera[:3, :3] @ point_camera) + reference_from_camera[:3, 3]

        print(f"Pixel ({x}, {y}) depth={depth_m:.4f} m")
        print(f"Camera point: [{point_camera[0]:.4f}, {point_camera[1]:.4f}, {point_camera[2]:.4f}]")
        print(
            f"Calibrated point ({reference_frame}): "
            f"[{point_reference[0]:.4f}, {point_reference[1]:.4f}, {point_reference[2]:.4f}]"
        )

        current_tcp_pose = arm_handle.get_actual_tcp_pose()
        current_tip = _current_tip_transform(current_tcp_pose, tip_offset_m)
        current_position = current_tip[:3, 3]
        print(
            f"Current tip point: "
            f"[{current_position[0]:.4f}, {current_position[1]:.4f}, {current_position[2]:.4f}]"
        )
        delta = current_position - point_reference
        print(f"Delta (tip - point): [{delta[0]:.4f}, {delta[1]:.4f}, {delta[2]:.4f}]")
        move_to_point(point_reference)

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
            if should_exit:
                break
            if key in {27, ord("q")}:
                break
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
        arm_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
