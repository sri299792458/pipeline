#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.calibration.ur import CalibrationArm, load_arm_connection_info
from data_pipeline.pipeline_utils import REPO_ROOT as PIPELINE_REPO_ROOT, normalize_active_arms, parse_task_list


DEFAULT_POSES_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "calibration_poses.local.json"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record wrist-calibration robot poses using UR tool-flange TCP.")
    parser.add_argument("--active-arms", required=True, help="Comma-separated arms: lightning, thunder, or lightning,thunder")
    parser.add_argument("--output-file", default=str(DEFAULT_POSES_FILE))
    parser.add_argument("--min-poses", type=int, default=5)
    return parser


def save_poses(path: Path, active_arms: list[str], poses: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "active_arms": active_arms,
        "tcp_frame_assumption": "tool_flange",
        "poses": poses,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> int:
    args = build_arg_parser().parse_args()
    active_arms = normalize_active_arms(parse_task_list(args.active_arms))
    if not active_arms:
        raise RuntimeError("No active arms selected for calibration pose recording.")

    arm_info = load_arm_connection_info(active_arms)
    missing = [arm for arm in active_arms if arm not in arm_info]
    if missing:
        raise RuntimeError(f"Missing runtime connection info for arms: {missing}")

    arms = {arm: CalibrationArm(info, connect_control=True) for arm, info in arm_info.items()}
    poses: list[dict[str, object]] = []
    try:
        for arm in active_arms:
            arms[arm].enable_freedrive()

        print("\nCalibration pose recording")
        print("==========================")
        print("UR TCP is assumed to be set to the tool flange.")
        print("Move the arm(s) in freedrive so the ChArUco board is well observed.")
        print("Commands:")
        print("  r  record current pose")
        print("  d  delete last pose")
        print("  l  list recorded poses")
        print("  q  save and quit")

        while True:
            command = input("\n[r/d/l/q] > ").strip().lower()
            if command == "r":
                pose_index = len(poses) + 1
                pose_entry: dict[str, object] = {
                    "name": f"pose_{pose_index:03d}",
                    "arms": {},
                }
                for arm in active_arms:
                    pose_entry["arms"][arm] = {
                        "joint_positions": arms[arm].get_actual_q(),
                        "tcp_pose": arms[arm].get_actual_tcp_pose(),
                    }
                poses.append(pose_entry)
                print(f"Recorded {pose_entry['name']}")
            elif command == "d":
                if not poses:
                    print("No poses to delete.")
                    continue
                removed = poses.pop()
                print(f"Deleted {removed['name']}")
            elif command == "l":
                if not poses:
                    print("No poses recorded yet.")
                    continue
                for index, pose in enumerate(poses, start=1):
                    print(f"{index:02d}: {pose['name']}")
            elif command == "q":
                if len(poses) < int(args.min_poses):
                    print(f"Need at least {args.min_poses} poses, currently have {len(poses)}.")
                    continue
                output_path = Path(args.output_file).expanduser()
                save_poses(output_path, active_arms, poses)
                print(f"Saved {len(poses)} poses to {output_path}")
                return 0
            else:
                print("Unknown command.")
    finally:
        for arm in active_arms:
            arms[arm].close()


if __name__ == "__main__":
    raise SystemExit(main())
