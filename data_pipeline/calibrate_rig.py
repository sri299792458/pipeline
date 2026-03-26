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
    calibrate_scene_camera_from_reference,
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
DEFAULT_RESULTS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "calibration.local.json"


@dataclass
class CameraObservation:
    pose_index: int
    pose_name: str
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


def _is_wrist_target(target: CameraTarget) -> bool:
    return target.mount_site.startswith("wrist_")


def _is_scene_target(target: CameraTarget) -> bool:
    return target.mount_site.startswith("scene_")


def _default_poses_path() -> Path | None:
    return DEFAULT_POSES_FILE if DEFAULT_POSES_FILE.exists() else None


def _reference_wrist_sort_key(target: CameraTarget) -> tuple[int, str]:
    # Lab default: when both wrists are available and no explicit reference is
    # requested, prefer Lightning as the scene-camera reference arm.
    if target.attached_to == "lightning":
        return (0, target.role)
    if target.attached_to == "thunder":
        return (1, target.role)
    return (2, target.role)


def _select_reference_wrist_target(
    wrist_targets: list[CameraTarget],
    reference_wrist_role: str | None,
) -> CameraTarget:
    if not wrist_targets:
        raise RuntimeError("Automatic scene-camera calibration requires at least one wrist camera role.")

    if reference_wrist_role:
        requested = str(reference_wrist_role).strip()
        for target in wrist_targets:
            if target.role == requested:
                return target
        raise RuntimeError(
            f"Reference wrist role {requested} was not selected. "
            f"Available wrist roles: {[target.role for target in wrist_targets]}"
        )

    return sorted(wrist_targets, key=_reference_wrist_sort_key)[0]


def _capture_pose_driven_observations(
    *,
    detector: CharucoDetector,
    targets: list[CameraTarget],
    poses_data: dict[str, Any],
    warmup_frames: int,
    stabilization_s: float,
    move_speed: float,
    move_acceleration: float,
) -> None:
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
            target.camera.warmup(warmup_frames)

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
                        pose_index=pose_index,
                        pose_name=pose_name,
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

def _build_wrist_camera_result(target: CameraTarget) -> tuple[dict[str, Any], np.ndarray | None]:
    intrinsics = target.camera.get_intrinsics()
    result = {
        "serial_number": target.serial_number,
        "model": target.model,
        "attached_to": target.attached_to,
        "mount_site": target.mount_site,
        "intrinsics": intrinsics,
    }

    hand_eye_observations = [obs for obs in target.observations if obs.base_to_flange is not None]
    hand_eye_result = calibrate_hand_eye(
        base_to_flange_transforms=[obs.base_to_flange for obs in hand_eye_observations if obs.base_to_flange is not None],
        target_to_camera_transforms=[obs.target_to_camera for obs in hand_eye_observations],
        reprojection_errors_px=[obs.reprojection_error_px for obs in hand_eye_observations],
    )
    result["type"] = "hand_eye"
    result["hand_eye_calibration"] = hand_eye_result

    flange_from_camera = None
    if hand_eye_result.get("success"):
        flange_from_camera = np.eye(4, dtype=np.float64)
        flange_from_camera[:3, :3] = np.asarray(hand_eye_result["rotation_matrix"], dtype=np.float64)
        flange_from_camera[:3, 3] = np.asarray(hand_eye_result["translation_vector"], dtype=np.float64)
    return result, flange_from_camera


def _build_scene_camera_result(
    *,
    target: CameraTarget,
    reference_wrist_target: CameraTarget,
    reference_flange_from_camera: np.ndarray | None,
) -> dict[str, Any]:
    intrinsics = target.camera.get_intrinsics()
    result = {
        "serial_number": target.serial_number,
        "model": target.model,
        "attached_to": target.attached_to,
        "mount_site": target.mount_site,
        "intrinsics": intrinsics,
        "type": "scene",
    }

    if reference_flange_from_camera is None:
        result["extrinsics"] = {
            "success": False,
            "error": f"Reference wrist calibration for {reference_wrist_target.role} did not succeed.",
        }
        return result

    reference_observations = {
        obs.pose_index: obs
        for obs in reference_wrist_target.observations
        if obs.base_to_flange is not None
    }
    base_to_target_transforms: list[np.ndarray] = []
    scene_target_to_camera_transforms: list[np.ndarray] = []
    reprojection_errors_px: list[float] = []

    for scene_obs in target.observations:
        reference_obs = reference_observations.get(scene_obs.pose_index)
        if reference_obs is None or reference_obs.base_to_flange is None:
            continue
        base_to_target = (
            np.asarray(reference_obs.base_to_flange, dtype=np.float64)
            @ reference_flange_from_camera
            @ np.asarray(reference_obs.target_to_camera, dtype=np.float64)
        )
        base_to_target_transforms.append(base_to_target)
        scene_target_to_camera_transforms.append(np.asarray(scene_obs.target_to_camera, dtype=np.float64))
        reprojection_errors_px.append(float(scene_obs.reprojection_error_px))

    reference_frame = f"{reference_wrist_target.attached_to}_base"
    result["extrinsics"] = calibrate_scene_camera_from_reference(
        base_to_target_transforms=base_to_target_transforms,
        target_to_camera_transforms=scene_target_to_camera_transforms,
        reprojection_errors_px=reprojection_errors_px,
        reference_frame=reference_frame,
        reference_camera_role=reference_wrist_target.role,
    )
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run V2 camera calibration for scene and wrist RealSense cameras.")
    parser.add_argument("--sensors-file", default=str(DEFAULT_SENSORS_FILE))
    parser.add_argument("--camera-role", action="append", default=[])
    parser.add_argument(
        "--reference-wrist-role",
        default="",
        help=(
            "Explicit wrist role to use as the scene-camera reference frame. "
            "If omitted and both wrists are available, lightning_wrist_1 is the default."
        ),
    )
    parser.add_argument("--poses-file", default="")
    parser.add_argument("--output-file", default=str(DEFAULT_RESULTS_FILE))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--warmup-frames", type=int, default=10)
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
    wrist_targets = [target for target in targets if _is_wrist_target(target)]
    scene_targets = [target for target in targets if _is_scene_target(target)]
    if scene_targets and not wrist_targets:
        available_targets = _sensor_targets(
            sensors_file=sensors_file,
            selected_roles=None,
            width=args.width,
            height=args.height,
            fps=args.fps,
        )
        available_wrist_targets = [target for target in available_targets if _is_wrist_target(target)]
        reference_wrist_target = _select_reference_wrist_target(
            available_wrist_targets,
            str(args.reference_wrist_role).strip() or None,
        )
        targets.append(reference_wrist_target)
        wrist_targets = [reference_wrist_target]
        print(
            f"Using reference wrist camera {reference_wrist_target.role} automatically "
            f"for scene calibration."
        )

    poses_path = (
        Path(args.poses_file).expanduser()
        if str(args.poses_file).strip()
        else _default_poses_path()
    )
    if poses_path is None:
        raise RuntimeError(
            "Calibration requires recorded wrist poses. Run data_pipeline/record_calibration_poses.py first "
            "or pass --poses-file explicitly."
        )

    poses_data = _load_pose_file(poses_path)
    _capture_pose_driven_observations(
        detector=detector,
        targets=targets,
        poses_data=poses_data,
        warmup_frames=int(args.warmup_frames),
        stabilization_s=float(args.stabilization_s),
        move_speed=float(args.move_speed),
        move_acceleration=float(args.move_acceleration),
    )

    results = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "charuco_config": board_config.to_dict(),
        "tcp_frame_assumption": "tool_flange",
        "poses_file": str(poses_path) if poses_path is not None else None,
        "cameras": {},
    }

    wrist_transforms: dict[str, np.ndarray | None] = {}
    for target in wrist_targets:
        wrist_result, flange_from_camera = _build_wrist_camera_result(target)
        wrist_transforms[target.role] = flange_from_camera
        results["cameras"][target.role] = wrist_result

    if scene_targets:
        reference_wrist_target = _select_reference_wrist_target(
            wrist_targets,
            str(args.reference_wrist_role).strip() or None,
        )
        results["reference_wrist_role"] = reference_wrist_target.role
        results["coordinate_frame"] = f"{reference_wrist_target.attached_to}_base"
        for target in scene_targets:
            results["cameras"][target.role] = _build_scene_camera_result(
                target=target,
                reference_wrist_target=reference_wrist_target,
                reference_flange_from_camera=wrist_transforms.get(reference_wrist_target.role),
            )

    output_path = Path(args.output_file).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
        handle.write("\n")
    print(f"Saved calibration results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
