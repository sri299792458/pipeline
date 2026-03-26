#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.calibration import (
    CalibrationArm,
    CharucoBoardConfig,
    CharucoDetector,
    RealSenseCalibrationCamera,
    calibrate_hand_eye,
    calibrate_scene_camera,
    load_arm_connection_info,
    pose6d_to_transform,
)
from data_pipeline.pipeline_utils import (
    REPO_ROOT as PIPELINE_REPO_ROOT,
    camera_path_parts_for_role,
    load_optional_sensor_overrides,
)


DEFAULT_SENSORS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "sensors.local.yaml"
DEFAULT_POSES_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "calibration_poses.local.json"
DEFAULT_WORLD_BOARD_PATH = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "world_board.local.json"
DEFAULT_RESULTS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "calibration.local.json"


@dataclass
class CameraObservation:
    target_to_camera: np.ndarray
    reprojection_error_px: float
    base_to_flange: np.ndarray | None = None


@dataclass
class CameraTarget:
    role: str
    serial_number: str
    model: str
    attached_to: str
    mount_site: str
    camera: RealSenseCalibrationCamera
    observations: list[CameraObservation] = field(default_factory=list)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_world_board_matrix(path: Path | None) -> np.ndarray | None:
    if path is None:
        return None
    matrix = np.asarray(_load_json(path), dtype=np.float64)
    if matrix.shape != (4, 4):
        raise ValueError(f"Expected a 4x4 matrix in {path}, got shape {matrix.shape}")
    return matrix


def _load_pose_file(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def _sensor_targets(
    sensors_file: Path,
    selected_roles: list[str] | None,
    width: int,
    height: int,
    fps: int,
) -> list[CameraTarget]:
    sensor_overrides = load_optional_sensor_overrides(sensors_file)
    targets: list[CameraTarget] = []
    requested = {role.strip() for role in (selected_roles or []) if role.strip()}
    for role, sensor in sensor_overrides.items():
        camera_parts = camera_path_parts_for_role(role)
        if camera_parts is None:
            continue
        if requested and role not in requested:
            continue
        serial_number = str(sensor.get("serial_number", "")).strip()
        if not serial_number:
            raise ValueError(f"Camera role {role} is missing serial_number in {sensors_file}")
        attached_to, mount_site = camera_parts
        targets.append(
            CameraTarget(
                role=role,
                serial_number=serial_number,
                model=str(sensor.get("model", "")).strip() or "Intel RealSense",
                attached_to=attached_to,
                mount_site=mount_site,
                camera=RealSenseCalibrationCamera(
                    name=role,
                    serial_number=serial_number,
                    width=width,
                    height=height,
                    fps=fps,
                ),
            )
        )
    if not targets:
        raise RuntimeError(f"No calibratable camera roles found in {sensors_file}")
    return targets


def _arm_from_role(role: str) -> str | None:
    camera_parts = camera_path_parts_for_role(role)
    if camera_parts is None:
        return None
    attachment, mount_site = camera_parts
    if mount_site.startswith("wrist_"):
        return attachment
    return None


def _capture_pose_driven_observations(
    *,
    detector: CharucoDetector,
    targets: list[CameraTarget],
    poses_data: dict[str, Any],
    stabilization_s: float,
    move_speed: float,
    move_acceleration: float,
) -> tuple[dict[str, CalibrationArm], list[str]]:
    active_arms = list(poses_data.get("active_arms", []))
    arm_handles = {
        arm: CalibrationArm(info, connect_control=True)
        for arm, info in load_arm_connection_info(active_arms).items()
    }
    pose_list = poses_data.get("poses", [])
    if not isinstance(pose_list, list) or not pose_list:
        raise RuntimeError("Pose file does not contain any poses.")

    try:
        for target in targets:
            target.camera.open()
            target.camera.warmup(10)

        for pose_index, pose in enumerate(pose_list, start=1):
            pose_name = str(pose.get("name", f"pose_{pose_index:03d}"))
            arms_block = pose.get("arms", {})
            print(f"\nPose {pose_index}/{len(pose_list)}: {pose_name}")
            for arm, handle in arm_handles.items():
                arm_pose = arms_block.get(arm)
                if not isinstance(arm_pose, dict):
                    continue
                joint_positions = arm_pose.get("joint_positions")
                if not isinstance(joint_positions, list):
                    continue
                print(f"  Moving {arm}...")
                handle.movej([float(value) for value in joint_positions], speed=move_speed, acceleration=move_acceleration)

            print(f"  Waiting {stabilization_s:.1f}s for stabilization...")
            time.sleep(stabilization_s)

            for target in targets:
                image = target.camera.grab_color()
                charuco_corners, charuco_ids = detector.detect(image)
                if charuco_corners is None or charuco_ids is None:
                    print(f"    {target.role}: board not detected")
                    continue
                intrinsics = target.camera.get_intrinsics()
                camera_matrix = np.asarray(intrinsics["camera_matrix"], dtype=np.float64)
                distortion = np.asarray(intrinsics["distortion_coeffs"], dtype=np.float64)
                rvec, tvec, reprojection_error_px = detector.estimate_board_pose(
                    charuco_corners,
                    charuco_ids,
                    camera_matrix,
                    distortion,
                )
                target_to_camera = np.eye(4, dtype=np.float64)
                target_to_camera[:3, :3] = pose6d_to_transform([0.0, 0.0, 0.0, *rvec])[:3, :3]
                target_to_camera[:3, 3] = tvec
                arm = _arm_from_role(target.role)
                base_to_flange = None
                if arm is not None:
                    base_to_flange = pose6d_to_transform(arm_handles[arm].get_actual_tcp_pose())
                target.observations.append(
                    CameraObservation(
                        target_to_camera=target_to_camera,
                        reprojection_error_px=reprojection_error_px,
                        base_to_flange=base_to_flange,
                    )
                )
                print(
                    f"    {target.role}: detected ({len(charuco_ids)} corners, reproj={reprojection_error_px:.2f}px)"
                )
    finally:
        for target in targets:
            target.camera.close()
        for handle in arm_handles.values():
            handle.close()
    return arm_handles, active_arms


def _capture_scene_only_observations(
    *,
    detector: CharucoDetector,
    targets: list[CameraTarget],
    warmup_frames: int,
    num_samples: int,
    max_frames: int,
    max_reprojection_error_px: float,
) -> None:
    try:
        for target in targets:
            target.camera.open()
            target.camera.warmup(warmup_frames)

        for target in targets:
            used_frames = 0
            while len(target.observations) < num_samples and used_frames < max_frames:
                image = target.camera.grab_color()
                used_frames += 1
                charuco_corners, charuco_ids = detector.detect(image)
                if charuco_corners is None or charuco_ids is None:
                    continue
                intrinsics = target.camera.get_intrinsics()
                camera_matrix = np.asarray(intrinsics["camera_matrix"], dtype=np.float64)
                distortion = np.asarray(intrinsics["distortion_coeffs"], dtype=np.float64)
                rvec, tvec, reprojection_error_px = detector.estimate_board_pose(
                    charuco_corners,
                    charuco_ids,
                    camera_matrix,
                    distortion,
                )
                if reprojection_error_px > max_reprojection_error_px:
                    continue
                target_to_camera = np.eye(4, dtype=np.float64)
                target_to_camera[:3, :3] = pose6d_to_transform([0.0, 0.0, 0.0, *rvec])[:3, :3]
                target_to_camera[:3, 3] = tvec
                target.observations.append(
                    CameraObservation(
                        target_to_camera=target_to_camera,
                        reprojection_error_px=reprojection_error_px,
                    )
                )
            print(
                f"{target.role}: collected {len(target.observations)} valid scene samples"
            )
    finally:
        for target in targets:
            target.camera.close()


def _build_camera_result(target: CameraTarget, world_from_board: np.ndarray | None) -> dict[str, Any]:
    intrinsics = target.camera.get_intrinsics()
    result = {
        "serial_number": target.serial_number,
        "model": target.model,
        "attached_to": target.attached_to,
        "mount_site": target.mount_site,
        "intrinsics": intrinsics,
    }

    if target.mount_site.startswith("wrist_"):
        hand_eye_observations = [obs for obs in target.observations if obs.base_to_flange is not None]
        hand_eye_result = calibrate_hand_eye(
            base_to_flange_transforms=[obs.base_to_flange for obs in hand_eye_observations if obs.base_to_flange is not None],
            target_to_camera_transforms=[obs.target_to_camera for obs in hand_eye_observations],
            reprojection_errors_px=[obs.reprojection_error_px for obs in hand_eye_observations],
        )
        result["type"] = "hand_eye"
        result["hand_eye_calibration"] = hand_eye_result
        return result

    if world_from_board is None:
        raise RuntimeError(f"Scene camera {target.role} requires --world-board-matrix.")
    scene_result = calibrate_scene_camera(
        target_to_camera_transforms=[obs.target_to_camera for obs in target.observations],
        world_from_target=world_from_board,
        reprojection_errors_px=[obs.reprojection_error_px for obs in target.observations],
        reference_frame="world",
    )
    result["type"] = "scene"
    result["extrinsics"] = scene_result
    return result


def _default_world_board_path() -> Path | None:
    return DEFAULT_WORLD_BOARD_PATH if DEFAULT_WORLD_BOARD_PATH.exists() else None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run V2 camera calibration for scene and wrist RealSense cameras.")
    parser.add_argument("--sensors-file", default=str(DEFAULT_SENSORS_FILE))
    parser.add_argument("--camera-role", action="append", default=[])
    parser.add_argument("--poses-file", default="")
    parser.add_argument("--world-board-matrix", default="")
    parser.add_argument("--output-file", default=str(DEFAULT_RESULTS_FILE))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--num-samples", type=int, default=30)
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--max-reprojection-error-px", type=float, default=2.0)
    parser.add_argument("--stabilization-s", type=float, default=1.0)
    parser.add_argument("--move-speed", type=float, default=0.6)
    parser.add_argument("--move-acceleration", type=float, default=0.8)
    parser.add_argument("--squares-x", type=int, default=9)
    parser.add_argument("--squares-y", type=int, default=9)
    parser.add_argument("--square-length", type=float, default=0.03)
    parser.add_argument("--marker-length", type=float, default=0.023)
    parser.add_argument("--dictionary", default="DICT_6X6_250")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    board_config = CharucoBoardConfig(
        squares_x=args.squares_x,
        squares_y=args.squares_y,
        square_length=args.square_length,
        marker_length=args.marker_length,
        dictionary=args.dictionary,
    )
    detector = CharucoDetector(board_config)
    sensors_file = Path(args.sensors_file).expanduser()
    targets = _sensor_targets(
        sensors_file=sensors_file,
        selected_roles=list(args.camera_role),
        width=args.width,
        height=args.height,
        fps=args.fps,
    )

    poses_path = Path(args.poses_file).expanduser() if str(args.poses_file).strip() else None
    world_board_path = (
        Path(args.world_board_matrix).expanduser()
        if str(args.world_board_matrix).strip()
        else _default_world_board_path()
    )
    world_from_board = _load_world_board_matrix(world_board_path)

    has_wrist_targets = any(target.mount_site.startswith("wrist_") for target in targets)
    if has_wrist_targets and poses_path is None:
        raise RuntimeError("Wrist-camera calibration requires --poses-file.")
    if not has_wrist_targets and world_from_board is None:
        raise RuntimeError("Scene-camera calibration requires --world-board-matrix or data_pipeline/configs/world_board.local.json.")

    poses_data = _load_pose_file(poses_path) if poses_path is not None else None
    if poses_data is not None:
        _capture_pose_driven_observations(
            detector=detector,
            targets=targets,
            poses_data=poses_data,
            stabilization_s=float(args.stabilization_s),
            move_speed=float(args.move_speed),
            move_acceleration=float(args.move_acceleration),
        )
    else:
        scene_targets = [target for target in targets if target.mount_site.startswith("scene_")]
        _capture_scene_only_observations(
            detector=detector,
            targets=scene_targets,
            warmup_frames=int(args.warmup_frames),
            num_samples=int(args.num_samples),
            max_frames=int(args.max_frames),
            max_reprojection_error_px=float(args.max_reprojection_error_px),
        )

    results = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "charuco_config": board_config.to_dict(),
        "tcp_frame_assumption": "tool_flange",
        "poses_file": str(poses_path) if poses_path is not None else None,
        "world_from_board": world_from_board.tolist() if world_from_board is not None else None,
        "cameras": {},
    }

    for target in targets:
        results["cameras"][target.role] = _build_camera_result(target, world_from_board)

    output_path = Path(args.output_file).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
        handle.write("\n")
    print(f"Saved calibration results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
