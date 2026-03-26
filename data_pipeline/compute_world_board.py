#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.calibration.core import pose6d_to_transform, save_matrix_json
from data_pipeline.pipeline_utils import REPO_ROOT as PIPELINE_REPO_ROOT


DEFAULT_WORLD_BOARD_PATH = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "world_board.local.json"


def _normalize(vector: np.ndarray, name: str) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError(f"{name} has zero length.")
    return vector / norm


def _contact_position(pose6d: tuple[float, ...], flange_to_contact_m: np.ndarray) -> np.ndarray:
    base_to_flange = pose6d_to_transform(np.asarray(pose6d, dtype=np.float64))
    return base_to_flange[:3, 3] + (base_to_flange[:3, :3] @ flange_to_contact_m)


def compute_world_board_from_corners(
    *,
    top_left: tuple[float, ...],
    top_right: tuple[float, ...],
    bottom_right: tuple[float, ...],
    bottom_left: tuple[float, ...],
    flange_to_contact_m: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    tl = _contact_position(top_left, flange_to_contact_m)
    tr = _contact_position(top_right, flange_to_contact_m)
    br = _contact_position(bottom_right, flange_to_contact_m)
    bl = _contact_position(bottom_left, flange_to_contact_m)

    points = np.stack([tl, tr, br, bl], axis=0)
    center = np.mean(points, axis=0)
    centered = points - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    plane_normal = _normalize(vh[-1], "plane_normal")

    x_raw = 0.5 * ((tr - tl) + (br - bl))
    y_raw = 0.5 * ((tl - bl) + (tr - br))
    x_axis = _normalize(x_raw - np.dot(x_raw, plane_normal) * plane_normal, "x_axis")
    y_axis = y_raw - np.dot(y_raw, plane_normal) * plane_normal
    y_axis = _normalize(y_axis - np.dot(y_axis, x_axis) * x_axis, "y_axis")
    z_axis = _normalize(np.cross(x_axis, y_axis), "z_axis")
    if float(np.dot(z_axis, plane_normal)) < 0.0:
        y_axis = -y_axis
        z_axis = -z_axis

    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = np.stack([x_axis, y_axis, z_axis], axis=1)
    transform[:3, 3] = center

    plane_distances = np.abs(centered @ z_axis)
    stats = {
        "plane_fit_rms_m": float(np.sqrt(np.mean(plane_distances ** 2))),
        "plane_fit_max_m": float(np.max(plane_distances)),
        "edge_top_m": float(np.linalg.norm(tr - tl)),
        "edge_right_m": float(np.linalg.norm(tr - br)),
        "edge_bottom_m": float(np.linalg.norm(br - bl)),
        "edge_left_m": float(np.linalg.norm(tl - bl)),
    }
    return transform, stats


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute T_world_board from four measured board corners.")
    parser.add_argument("--top-left", type=float, nargs=6, required=True, metavar=("X", "Y", "Z", "RX", "RY", "RZ"))
    parser.add_argument("--top-right", type=float, nargs=6, required=True, metavar=("X", "Y", "Z", "RX", "RY", "RZ"))
    parser.add_argument("--bottom-right", type=float, nargs=6, required=True, metavar=("X", "Y", "Z", "RX", "RY", "RZ"))
    parser.add_argument("--bottom-left", type=float, nargs=6, required=True, metavar=("X", "Y", "Z", "RX", "RY", "RZ"))
    parser.add_argument("--flange-to-contact-m", type=float, nargs=3, default=(0.0, 0.0, 0.162), metavar=("X", "Y", "Z"))
    parser.add_argument("--output-file", default=str(DEFAULT_WORLD_BOARD_PATH))
    parser.add_argument("--print-only", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    transform, stats = compute_world_board_from_corners(
        top_left=tuple(args.top_left),
        top_right=tuple(args.top_right),
        bottom_right=tuple(args.bottom_right),
        bottom_left=tuple(args.bottom_left),
        flange_to_contact_m=np.asarray(args.flange_to_contact_m, dtype=np.float64),
    )

    print("T_world_board:")
    for row in transform:
        print(row.tolist())
    print(
        "Plane fit residuals (m): "
        f"rms={stats['plane_fit_rms_m']:.6f}, max={stats['plane_fit_max_m']:.6f}"
    )
    print(
        "Measured edge lengths (m): "
        f"top={stats['edge_top_m']:.6f}, right={stats['edge_right_m']:.6f}, "
        f"bottom={stats['edge_bottom_m']:.6f}, left={stats['edge_left_m']:.6f}"
    )

    if args.print_only:
        return 0

    output_path = Path(args.output_file).expanduser()
    save_matrix_json(output_path, transform)
    print(f"Saved world-board transform to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
