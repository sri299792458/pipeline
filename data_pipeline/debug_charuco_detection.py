#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import pyrealsense2 as rs

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.calibration.core import _aruco_dictionary, _make_charuco_board, _make_detector_parameters
from data_pipeline.pipeline_utils import REPO_ROOT as PIPELINE_REPO_ROOT, load_optional_sensor_overrides


DEFAULT_SENSORS_FILE = PIPELINE_REPO_ROOT / "data_pipeline" / "configs" / "sensors.local.yaml"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Live debug view for ArUco/ChArUco detection on one RealSense camera. "
            "This helps separate 'wrong dictionary family' from 'wrong board layout' problems."
        )
    )
    parser.add_argument("--camera", required=True)
    parser.add_argument("--sensors-file", default=str(DEFAULT_SENSORS_FILE))
    parser.add_argument("--dictionary", default="DICT_4X4_50")
    parser.add_argument("--squares-x", type=int, default=6)
    parser.add_argument("--squares-y", type=int, default=9)
    parser.add_argument("--square-length", type=float, default=0.03)
    parser.add_argument("--marker-length", type=float, default=0.022)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--save-annotated-dir",
        default="",
        help="Optional directory to periodically save annotated debug frames.",
    )
    return parser


def _load_serial_number(sensors_file: str, camera: str) -> str:
    sensors = load_optional_sensor_overrides(sensors_file)
    sensor = sensors.get(camera)
    if not isinstance(sensor, dict):
        raise KeyError(f"Camera {camera} not found in {sensors_file}")
    serial_number = str(sensor.get("serial_number", "")).strip()
    if not serial_number:
        raise RuntimeError(f"Camera {camera} is missing serial_number in {sensors_file}")
    return serial_number


def _detect_markers(gray: np.ndarray, dictionary, parameters):
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, parameters)
        return detector.detectMarkers(gray)
    return cv2.aruco.detectMarkers(gray, dictionary, parameters=parameters)


def _overlay_status(
    image: np.ndarray,
    *,
    camera: str,
    dictionary_name: str,
    squares_x: int,
    squares_y: int,
    marker_count: int,
    charuco_count: int,
    marker_ids: np.ndarray | None,
) -> np.ndarray:
    overlay = image.copy()
    lines = [
        f"{camera}",
        f"{dictionary_name} {squares_x}x{squares_y}",
        f"markers={marker_count} charuco={charuco_count}",
    ]
    if marker_ids is not None and len(marker_ids) > 0:
        ids = [str(int(value)) for value in marker_ids.reshape(-1)[:12]]
        suffix = "..." if len(marker_ids) > 12 else ""
        lines.append(f"ids={','.join(ids)}{suffix}")
    y = 28
    for line in lines:
        cv2.putText(
            overlay,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (30, 255, 30),
            2,
            cv2.LINE_AA,
        )
        y += 28
    return overlay


def main() -> int:
    args = build_arg_parser().parse_args()
    serial_number = _load_serial_number(args.sensors_file, args.camera)

    dictionary = _aruco_dictionary(args.dictionary)
    parameters = _make_detector_parameters()
    board = _make_charuco_board(
        type(
            "TmpBoard",
            (),
            {
                "squares_x": args.squares_x,
                "squares_y": args.squares_y,
                "square_length": args.square_length,
                "marker_length": args.marker_length,
                "dictionary": args.dictionary,
            },
        )()
    )

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial_number)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    profile = pipeline.start(config)
    device = profile.get_device()
    try:
        device_name = device.get_info(rs.camera_info.name)
    except Exception:
        device_name = "Intel RealSense"

    print(
        f"Debugging {args.camera} ({device_name} {serial_number}) "
        f"at {args.width}x{args.height}@{args.fps}"
    )
    print(f"Board config: {args.dictionary} {args.squares_x}x{args.squares_y}")
    print("Press q or Esc to quit if a window is available, otherwise Ctrl-C.")

    window_name = f"charuco-debug-{args.camera}"
    show_window = True
    try:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    except cv2.error:
        show_window = False
        print("OpenCV HighGUI is unavailable; running in console-only mode.")

    save_dir = Path(args.save_annotated_dir).expanduser() if str(args.save_annotated_dir).strip() else None
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving annotated frames to {save_dir}")
    last_log_time = 0.0
    last_save_time = 0.0
    last_signature: tuple[int, int, tuple[int, ...]] | None = None

    try:
        while True:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue

            color = np.asanyarray(color_frame.get_data())
            gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

            marker_corners, marker_ids, _ = _detect_markers(gray, dictionary, parameters)
            marker_count = len(marker_ids) if marker_ids is not None else 0
            charuco_count = 0
            charuco_corners = None
            charuco_ids = None

            annotated = color.copy()
            if marker_ids is not None and len(marker_ids) > 0:
                cv2.aruco.drawDetectedMarkers(annotated, marker_corners, marker_ids)
                detected, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
                    marker_corners,
                    marker_ids,
                    gray,
                    board,
                )
                if detected is not None and int(detected) >= 1 and charuco_corners is not None and charuco_ids is not None:
                    charuco_count = int(len(charuco_ids))
                    cv2.aruco.drawDetectedCornersCharuco(annotated, charuco_corners, charuco_ids)

            ids_tuple = tuple(int(value) for value in marker_ids.reshape(-1)) if marker_ids is not None else ()
            signature = (marker_count, charuco_count, ids_tuple)
            now = time.time()
            if signature != last_signature or (now - last_log_time) >= 1.0:
                print(
                    f"markers={marker_count} charuco={charuco_count} "
                    f"ids={list(ids_tuple[:12])}{'...' if len(ids_tuple) > 12 else ''}"
                )
                last_signature = signature
                last_log_time = now

            annotated = _overlay_status(
                annotated,
                camera=args.camera,
                dictionary_name=args.dictionary,
                squares_x=args.squares_x,
                squares_y=args.squares_y,
                marker_count=marker_count,
                charuco_count=charuco_count,
                marker_ids=marker_ids,
            )
            if save_dir is not None and (now - last_save_time) >= 1.0:
                output_path = save_dir / f"{args.camera}.latest.png"
                cv2.imwrite(str(output_path), annotated)
                last_save_time = now
            if show_window:
                cv2.imshow(window_name, annotated)
                key = cv2.waitKey(1) & 0xFF
                if key in {27, ord("q")}:
                    break
    finally:
        pipeline.stop()
        if show_window:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
