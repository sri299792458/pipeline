from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def _aruco_dictionary(dictionary_name: str):
    if not hasattr(cv2, "aruco"):
        raise ImportError("cv2.aruco is missing. Install opencv-contrib-python.")
    if not hasattr(cv2.aruco, dictionary_name):
        raise ValueError(f"Unknown ArUco dictionary: {dictionary_name}")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary_name))


@dataclass(frozen=True)
class CharucoBoardConfig:
    squares_x: int = 6
    squares_y: int = 9
    square_length: float = 0.03
    marker_length: float = 0.022
    dictionary: str = "DICT_4X4_50"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _make_charuco_board(config: CharucoBoardConfig):
    dictionary = _aruco_dictionary(config.dictionary)
    if hasattr(cv2.aruco, "CharucoBoard"):
        return cv2.aruco.CharucoBoard(
            (config.squares_x, config.squares_y),
            config.square_length,
            config.marker_length,
            dictionary,
        )
    return cv2.aruco.CharucoBoard_create(
        config.squares_x,
        config.squares_y,
        config.square_length,
        config.marker_length,
        dictionary,
    )


def _make_detector_parameters():
    if hasattr(cv2.aruco, "DetectorParameters"):
        return cv2.aruco.DetectorParameters()
    return cv2.aruco.DetectorParameters_create()


def rotvec_to_matrix(rotvec: np.ndarray) -> np.ndarray:
    rotation_matrix, _ = cv2.Rodrigues(np.asarray(rotvec, dtype=np.float64).reshape(3, 1))
    return rotation_matrix.astype(np.float64)


def matrix_to_rotvec(rotation_matrix: np.ndarray) -> np.ndarray:
    rotvec, _ = cv2.Rodrigues(np.asarray(rotation_matrix, dtype=np.float64))
    return rotvec.reshape(3).astype(np.float64)


def pose6d_to_transform(pose: list[float] | tuple[float, ...] | np.ndarray) -> np.ndarray:
    pose_array = np.asarray(pose, dtype=np.float64).reshape(6)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotvec_to_matrix(pose_array[3:])
    transform[:3, 3] = pose_array[:3]
    return transform


def invert_transform(transform: np.ndarray) -> np.ndarray:
    transform = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    inverse = np.eye(4, dtype=np.float64)
    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    inverse[:3, :3] = rotation.T
    inverse[:3, 3] = -(rotation.T @ translation)
    return inverse


def average_transforms(transforms: list[np.ndarray]) -> np.ndarray:
    if not transforms:
        raise ValueError("No transforms to average.")
    rotations = Rotation.from_matrix([np.asarray(transform, dtype=np.float64)[:3, :3] for transform in transforms])
    mean_rotation = rotations.mean().as_matrix()
    mean_translation = np.mean([np.asarray(transform, dtype=np.float64)[:3, 3] for transform in transforms], axis=0)
    mean_transform = np.eye(4, dtype=np.float64)
    mean_transform[:3, :3] = mean_rotation
    mean_transform[:3, 3] = mean_translation
    return mean_transform


def _rotation_angle_deg(reference_rotation: np.ndarray, sample_rotation: np.ndarray) -> float:
    relative = np.asarray(reference_rotation, dtype=np.float64).T @ np.asarray(sample_rotation, dtype=np.float64)
    cosine = np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def _transform_spread(transforms: list[np.ndarray], mean_transform: np.ndarray) -> dict[str, Any]:
    translations = np.stack([np.asarray(transform, dtype=np.float64)[:3, 3] for transform in transforms], axis=0)
    rotation_errors_deg = [
        _rotation_angle_deg(mean_transform[:3, :3], np.asarray(transform, dtype=np.float64)[:3, :3])
        for transform in transforms
    ]
    return {
        "translation_std_m": np.std(translations, axis=0).astype(np.float64).tolist(),
        "rotation_error_mean_deg": float(np.mean(rotation_errors_deg)),
        "rotation_error_std_deg": float(np.std(rotation_errors_deg)),
    }


def _reprojection_error_px(
    board,
    charuco_corners: np.ndarray,
    charuco_ids: np.ndarray,
    rvec: np.ndarray,
    tvec: np.ndarray,
    camera_matrix: np.ndarray,
    distortion_coeffs: np.ndarray,
) -> float:
    object_points = board.getChessboardCorners()[charuco_ids.reshape(-1)]
    projected, _ = cv2.projectPoints(
        object_points,
        np.asarray(rvec, dtype=np.float64),
        np.asarray(tvec, dtype=np.float64),
        np.asarray(camera_matrix, dtype=np.float64),
        np.asarray(distortion_coeffs, dtype=np.float64),
    )
    projected = projected.reshape(-1, 2)
    observed = np.asarray(charuco_corners, dtype=np.float64).reshape(-1, 2)
    return float(np.linalg.norm(projected - observed, axis=1).mean())


class CharucoDetector:
    def __init__(self, config: CharucoBoardConfig):
        self.config = config
        self.dictionary = _aruco_dictionary(config.dictionary)
        self.parameters = _make_detector_parameters()
        self.board = _make_charuco_board(config)

    def detect(self, image: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(self.dictionary, self.parameters)
            marker_corners, marker_ids, _ = detector.detectMarkers(gray)
        else:
            marker_corners, marker_ids, _ = cv2.aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)

        if marker_ids is None or len(marker_ids) == 0:
            return None, None

        detected, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners,
            marker_ids,
            gray,
            self.board,
        )
        if detected is None or int(detected) < 4 or charuco_corners is None or charuco_ids is None:
            return None, None
        return charuco_corners, charuco_ids

    def estimate_board_pose(
        self,
        charuco_corners: np.ndarray,
        charuco_ids: np.ndarray,
        camera_matrix: np.ndarray,
        distortion_coeffs: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        success, rvec, tvec = cv2.aruco.estimatePoseCharucoBoard(
            np.asarray(charuco_corners, dtype=np.float32),
            np.asarray(charuco_ids, dtype=np.int32),
            self.board,
            np.asarray(camera_matrix, dtype=np.float64),
            np.asarray(distortion_coeffs, dtype=np.float64),
            None,
            None,
        )
        if not success:
            raise RuntimeError("Failed to estimate ChArUco board pose.")
        reproj_error_px = _reprojection_error_px(
            self.board,
            charuco_corners,
            charuco_ids,
            rvec,
            tvec,
            camera_matrix,
            distortion_coeffs,
        )
        return (
            np.asarray(rvec, dtype=np.float64).reshape(3),
            np.asarray(tvec, dtype=np.float64).reshape(3),
            reproj_error_px,
        )


def _hand_eye_method_name(method: int) -> str:
    method_names = {
        cv2.CALIB_HAND_EYE_TSAI: "CALIB_HAND_EYE_TSAI",
        cv2.CALIB_HAND_EYE_PARK: "CALIB_HAND_EYE_PARK",
        cv2.CALIB_HAND_EYE_HORAUD: "CALIB_HAND_EYE_HORAUD",
        cv2.CALIB_HAND_EYE_ANDREFF: "CALIB_HAND_EYE_ANDREFF",
        cv2.CALIB_HAND_EYE_DANIILIDIS: "CALIB_HAND_EYE_DANIILIDIS",
    }
    return method_names.get(method, f"UNKNOWN_{method}")


def calibrate_hand_eye(
    *,
    base_to_flange_transforms: list[np.ndarray],
    target_to_camera_transforms: list[np.ndarray],
    reprojection_errors_px: list[float] | None = None,
    method: int = cv2.CALIB_HAND_EYE_TSAI,
    tcp_frame_assumption: str = "tool_flange",
) -> dict[str, Any]:
    if len(base_to_flange_transforms) != len(target_to_camera_transforms):
        raise ValueError("base_to_flange_transforms and target_to_camera_transforms must have the same length.")
    if len(base_to_flange_transforms) < 3:
        return {"success": False, "error": "Need at least 3 pose pairs for hand-eye calibration."}

    rotation_gripper_to_base = [transform[:3, :3] for transform in base_to_flange_transforms]
    translation_gripper_to_base = [transform[:3, 3] for transform in base_to_flange_transforms]
    rotation_target_to_camera = [transform[:3, :3] for transform in target_to_camera_transforms]
    translation_target_to_camera = [transform[:3, 3] for transform in target_to_camera_transforms]

    rotation_camera_to_flange, translation_camera_to_flange = cv2.calibrateHandEye(
        rotation_gripper_to_base,
        translation_gripper_to_base,
        rotation_target_to_camera,
        translation_target_to_camera,
        method=method,
    )

    flange_from_camera = np.eye(4, dtype=np.float64)
    flange_from_camera[:3, :3] = np.asarray(rotation_camera_to_flange, dtype=np.float64)
    flange_from_camera[:3, 3] = np.asarray(translation_camera_to_flange, dtype=np.float64).reshape(3)

    base_to_target_estimates: list[np.ndarray] = []
    for base_to_flange, target_to_camera in zip(base_to_flange_transforms, target_to_camera_transforms):
        base_to_target_estimates.append(base_to_flange @ flange_from_camera @ target_to_camera)
    mean_base_to_target = average_transforms(base_to_target_estimates)
    spread = _transform_spread(base_to_target_estimates, mean_base_to_target)

    result = {
        "success": True,
        "reference_frame": tcp_frame_assumption,
        "robot_pose_source": "rtde_actual_tcp_pose",
        "num_pose_pairs": len(base_to_flange_transforms),
        "method": _hand_eye_method_name(method),
        "rotation_matrix": flange_from_camera[:3, :3].tolist(),
        "translation_vector": flange_from_camera[:3, 3].tolist(),
        "rotation_vector": matrix_to_rotvec(flange_from_camera[:3, :3]).tolist(),
        "target_pose_consistency": {
            "reference_frame": "robot_base",
            "mean_transform": mean_base_to_target.tolist(),
            **spread,
        },
    }
    if reprojection_errors_px:
        result["reprojection_error_mean_px"] = float(np.mean(reprojection_errors_px))
        result["reprojection_error_std_px"] = float(np.std(reprojection_errors_px))
    return result


def calibrate_scene_camera_from_reference(
    *,
    base_to_target_transforms: list[np.ndarray],
    target_to_camera_transforms: list[np.ndarray],
    reprojection_errors_px: list[float] | None = None,
    reference_frame: str,
    reference_camera: str,
) -> dict[str, Any]:
    if len(base_to_target_transforms) != len(target_to_camera_transforms):
        raise ValueError("base_to_target_transforms and target_to_camera_transforms must have the same length.")
    if not base_to_target_transforms:
        return {"success": False, "error": "Need at least 1 matched pose pair for scene calibration."}

    base_to_camera_estimates = [
        np.asarray(base_to_target, dtype=np.float64).reshape(4, 4) @ invert_transform(target_to_camera)
        for base_to_target, target_to_camera in zip(base_to_target_transforms, target_to_camera_transforms)
    ]
    mean_base_to_camera = average_transforms(base_to_camera_estimates)
    spread = _transform_spread(base_to_camera_estimates, mean_base_to_camera)

    result = {
        "success": True,
        "reference_frame": reference_frame,
        "reference_camera": reference_camera,
        "num_samples": len(base_to_camera_estimates),
        "rotation_matrix": mean_base_to_camera[:3, :3].tolist(),
        "translation_vector": mean_base_to_camera[:3, 3].tolist(),
        "rotation_vector": matrix_to_rotvec(mean_base_to_camera[:3, :3]).tolist(),
        "base_to_camera_samples": {
            "mean_transform": mean_base_to_camera.tolist(),
            **spread,
        },
    }
    if reprojection_errors_px:
        result["reprojection_error_mean_px"] = float(np.mean(reprojection_errors_px))
        result["reprojection_error_std_px"] = float(np.std(reprojection_errors_px))
    return result


def calibrate_scene_camera(
    *,
    target_to_camera_transforms: list[np.ndarray],
    world_from_target: np.ndarray,
    reprojection_errors_px: list[float] | None = None,
    reference_frame: str = "world",
) -> dict[str, Any]:
    if not target_to_camera_transforms:
        return {"success": False, "error": "Need at least 1 board observation for scene calibration."}

    world_to_camera_estimates = [
        np.asarray(world_from_target, dtype=np.float64).reshape(4, 4) @ invert_transform(target_to_camera)
        for target_to_camera in target_to_camera_transforms
    ]
    mean_world_to_camera = average_transforms(world_to_camera_estimates)
    spread = _transform_spread(world_to_camera_estimates, mean_world_to_camera)

    result = {
        "success": True,
        "reference_frame": reference_frame,
        "num_samples": len(target_to_camera_transforms),
        "rotation_matrix": mean_world_to_camera[:3, :3].tolist(),
        "translation_vector": mean_world_to_camera[:3, 3].tolist(),
        "rotation_vector": matrix_to_rotvec(mean_world_to_camera[:3, :3]).tolist(),
        "world_to_camera_samples": {
            "mean_transform": mean_world_to_camera.tolist(),
            **spread,
        },
    }
    if reprojection_errors_px:
        result["reprojection_error_mean_px"] = float(np.mean(reprojection_errors_px))
        result["reprojection_error_std_px"] = float(np.std(reprojection_errors_px))
    return result


def save_matrix_json(path: str | Path, matrix: np.ndarray) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(np.asarray(matrix, dtype=np.float64).tolist(), handle, indent=2)
        handle.write("\n")
