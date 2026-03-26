from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pyrealsense2 as rs


@dataclass
class RealSenseCalibrationCamera:
    name: str
    serial_number: str
    width: int = 1280
    height: int = 720
    fps: int = 30

    def __post_init__(self) -> None:
        self._pipeline: rs.pipeline | None = None
        self._profile: rs.pipeline_profile | None = None
        self._intrinsics: dict[str, Any] | None = None
        self._model: str | None = None

    def open(self) -> None:
        if self._pipeline is not None:
            return
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(self.serial_number)
        config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
        profile = pipeline.start(config)
        device = profile.get_device()
        try:
            self._model = device.get_info(rs.camera_info.name)
        except Exception:
            self._model = "Intel RealSense"

        color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
        intr = color_stream.get_intrinsics()
        self._intrinsics = {
            "camera_matrix": [
                [float(intr.fx), 0.0, float(intr.ppx)],
                [0.0, float(intr.fy), float(intr.ppy)],
                [0.0, 0.0, 1.0],
            ],
            "distortion_coeffs": [float(value) for value in intr.coeffs],
            "image_size": [int(intr.width), int(intr.height)],
            "source": "realsense_factory_calibration",
        }
        self._pipeline = pipeline
        self._profile = profile

    @property
    def model(self) -> str:
        return self._model or "Intel RealSense"

    def warmup(self, frame_count: int) -> None:
        self.open()
        assert self._pipeline is not None
        for _ in range(max(0, int(frame_count))):
            self._pipeline.wait_for_frames()

    def grab_color(self) -> np.ndarray:
        self.open()
        assert self._pipeline is not None
        frames = self._pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        if not color_frame:
            raise RuntimeError(f"Failed to acquire color frame for {self.name} ({self.serial_number}).")
        return np.asanyarray(color_frame.get_data()).copy()

    def get_intrinsics(self) -> dict[str, Any]:
        self.open()
        assert self._intrinsics is not None
        return self._intrinsics

    def close(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
        self._pipeline = None
        self._profile = None
