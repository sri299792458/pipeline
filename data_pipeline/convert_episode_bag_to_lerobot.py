#!/usr/bin/env python3

"""Convert one raw V2 rosbag episode into the published LeRobot dataset."""

from __future__ import annotations

import argparse
import copy
import io
import json
import math
import shutil
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imageio.v2 as imageio
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rosbag2_py
import yaml
from geometry_msgs.msg import PoseStamped, WrenchStamped
from PIL import Image as PILImage
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import Bool

try:
    from realsense2_camera_msgs.msg import Metadata
except ImportError:
    Metadata = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import (  # noqa: E402
    detect_bag_storage_id,
    effective_profile_for_session,
    load_profile,
    manifest_active_arms,
    manifest_clock_policy,
    manifest_dataset_id,
    manifest_episode_id,
    manifest_language_instruction,
    manifest_profile_name,
    manifest_robot_id,
    manifest_sensors,
    manifest_task_name,
    manifest_topic_types,
    normalize_active_arms,
    profile_required_arms,
    write_json,
)
from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

MAX_DEPTH_U16 = 0x10000
REALSENSE_COLOR_MAP_STEPS = 4000
REALSENSE_JET_STOPS = np.asarray(
    [
        [0.0, 0.0, 255.0],
        [0.0, 255.0, 255.0],
        [255.0, 255.0, 0.0],
        [255.0, 0.0, 0.0],
        [50.0, 0.0, 0.0],
    ],
    dtype=np.float32,
)


@dataclass
class TopicSeries:
    topic: str
    type_name: str
    timestamps_ns: list[int]
    values: list[Any]
    bag_timestamps_ns: list[int]

    def __post_init__(self) -> None:
        self._ts_array: np.ndarray | None = None

    @property
    def ts_array(self) -> np.ndarray:
        if self._ts_array is None:
            self._ts_array = np.asarray(self.timestamps_ns, dtype=np.int64)
        return self._ts_array

    def first_ts(self) -> int:
        if not self.timestamps_ns:
            raise ValueError(f"No samples recorded for topic {self.topic}")
        return self.timestamps_ns[0]

    def last_ts(self) -> int:
        if not self.timestamps_ns:
            raise ValueError(f"No samples recorded for topic {self.topic}")
        return self.timestamps_ns[-1]

    def latest_before(self, target_ns: int) -> tuple[Any, int] | None:
        idx = bisect_right(self.timestamps_ns, target_ns) - 1
        if idx < 0:
            return None
        ts_ns = self.timestamps_ns[idx]
        return self.values[idx], target_ns - ts_ns

    def latest_before_index(self, target_ns: int) -> tuple[int, int] | None:
        idx = bisect_right(self.timestamps_ns, target_ns) - 1
        if idx < 0:
            return None
        ts_ns = self.timestamps_ns[idx]
        return idx, target_ns - ts_ns

    def nearest(self, target_ns: int) -> tuple[Any, int] | None:
        idx = bisect_left(self.timestamps_ns, target_ns)
        candidates: list[tuple[Any, int]] = []
        if idx < len(self.timestamps_ns):
            candidates.append((self.values[idx], abs(self.timestamps_ns[idx] - target_ns)))
        if idx > 0:
            candidates.append((self.values[idx - 1], abs(self.timestamps_ns[idx - 1] - target_ns)))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])

    def nearest_index(self, target_ns: int) -> tuple[int, int] | None:
        idx = bisect_left(self.timestamps_ns, target_ns)
        candidates: list[tuple[int, int]] = []
        if idx < len(self.timestamps_ns):
            candidates.append((idx, abs(self.timestamps_ns[idx] - target_ns)))
        if idx > 0:
            candidates.append((idx - 1, abs(self.timestamps_ns[idx - 1] - target_ns)))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])

    def diagnostics(self) -> dict[str, Any]:
        if len(self.timestamps_ns) < 2:
            return {
                "count": len(self.timestamps_ns),
                "observed_rate_hz": 0.0,
                "inter_arrival_ms": None,
            }

        ts = self.ts_array
        diffs_ms = np.diff(ts).astype(np.float64) / 1_000_000.0
        duration_s = (ts[-1] - ts[0]) / 1_000_000_000.0
        observed_rate_hz = (len(ts) - 1) / duration_s if duration_s > 0 else 0.0
        return {
            "count": int(len(ts)),
            "observed_rate_hz": observed_rate_hz,
            "inter_arrival_ms": {
                "min": float(diffs_ms.min()),
                "max": float(diffs_ms.max()),
                "mean": float(diffs_ms.mean()),
                "std": float(diffs_ms.std()),
            },
        }


@dataclass
class AlignmentFailure:
    frame_index: int
    timestamp_ns: int
    reason: str


@dataclass
class DepthSelection:
    field: str
    topic: str
    sample_index: int
    frame_index: int
    timestamp_ns: int
    skew_ms: float


@dataclass
class ActiveInterval:
    start_ns: int
    end_ns: int


def stamp_to_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def quaternion_to_rpy(x: float, y: float, z: float, w: float) -> tuple[float, float, float]:
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


def decode_image_to_rgb(msg: Image) -> np.ndarray:
    encoding = msg.encoding.lower()
    if encoding in {"rgb8", "8uc3"}:
        array = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        return array.copy()
    if encoding == "bgr8":
        array = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        return array[:, :, ::-1].copy()
    if encoding == "rgba8":
        array = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 4)
        return array[:, :, :3].copy()
    if encoding == "bgra8":
        array = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 4)
        return array[:, :, 2::-1].copy()
    if encoding in {"mono8", "8uc1"}:
        array = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
        return np.repeat(array[:, :, None], 3, axis=2)
    raise ValueError(f"Unsupported image encoding for published RGB conversion: {msg.encoding}")


def decode_image_to_depth(msg: Image) -> np.ndarray:
    encoding = msg.encoding.lower()
    if encoding in {"16uc1", "mono16"}:
        return np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width).copy()
    raise ValueError(f"Unsupported image encoding for published depth conversion: {msg.encoding}")


def encode_depth_png16(depth: np.ndarray) -> bytes:
    if depth.dtype != np.uint16:
        raise ValueError(f"Expected uint16 depth array, got {depth.dtype}")
    if depth.ndim != 2:
        raise ValueError(f"Expected 2D depth array, got shape {depth.shape}")
    image = PILImage.fromarray(depth)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_realsense_color_map_cache() -> np.ndarray:
    last_stop = REALSENSE_JET_STOPS.shape[0] - 1
    positions = np.linspace(0.0, float(last_stop), REALSENSE_COLOR_MAP_STEPS + 1, dtype=np.float32)
    lower = np.floor(positions).astype(np.int32)
    upper = np.clip(lower + 1, 0, last_stop)
    local_t = (positions - lower).reshape(-1, 1)
    cache = REALSENSE_JET_STOPS[lower] * (1.0 - local_t) + REALSENSE_JET_STOPS[upper] * local_t
    return np.rint(cache).astype(np.uint8)


REALSENSE_JET_CACHE = build_realsense_color_map_cache()


def colorize_depth_realsense_preview(depth: np.ndarray) -> np.ndarray:
    if depth.dtype != np.uint16:
        raise ValueError(f"Expected uint16 depth array, got {depth.dtype}")
    if depth.ndim != 2:
        raise ValueError(f"Expected 2D depth array for preview colorization, got shape {depth.shape}")

    histogram = np.bincount(depth.reshape(-1), minlength=MAX_DEPTH_U16).astype(np.int64, copy=False)
    cumulative = np.empty_like(histogram)
    cumulative[0] = histogram[0]
    cumulative[1:] = np.cumsum(histogram[1:], dtype=np.int64)
    total_colored_pixels = int(cumulative[-1])

    rgb = np.zeros((depth.shape[0], depth.shape[1], 3), dtype=np.uint8)
    if total_colored_pixels <= 0:
        return rgb

    valid_mask = depth > 0
    if not np.any(valid_mask):
        return rgb

    normalized = cumulative[depth[valid_mask]].astype(np.float32) / float(total_colored_pixels)
    cache_indices = np.clip((normalized * REALSENSE_COLOR_MAP_STEPS).astype(np.int32), 0, REALSENSE_COLOR_MAP_STEPS)
    rgb[valid_mask] = REALSENSE_JET_CACHE[cache_indices]
    return rgb


def extract_message_timestamp_ns(msg: Any, bag_timestamp_ns: int) -> int:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return bag_timestamp_ns
    return stamp_to_ns(stamp) or bag_timestamp_ns


def parse_message(topic: str, msg: Any, bag_timestamp_ns: int, parse_value: bool) -> tuple[int, Any]:
    ts_ns = extract_message_timestamp_ns(msg, bag_timestamp_ns)
    if not parse_value:
        return ts_ns, None

    if Metadata is not None and isinstance(msg, Metadata):
        payload = json.loads(msg.json_data)
        return ts_ns, payload

    if isinstance(msg, Image):
        return ts_ns, decode_image_to_rgb(msg)

    if isinstance(msg, JointState):
        positions = np.asarray(msg.position, dtype=np.float32)
        if topic.endswith("/joint_state") or topic.endswith("/cmd_joint_state"):
            if positions.shape[0] < 6:
                raise ValueError(f"Expected at least 6 joint positions on {topic}, got {positions.shape[0]}")
            return ts_ns, positions[:6]
        if positions.shape[0] < 1:
            raise ValueError(f"Expected at least 1 gripper position on {topic}")
        return ts_ns, np.asarray([positions[0]], dtype=np.float32)

    if isinstance(msg, PoseStamped):
        q = msg.pose.orientation
        roll, pitch, yaw = quaternion_to_rpy(q.x, q.y, q.z, q.w)
        value = np.asarray(
            [
                msg.pose.position.x,
                msg.pose.position.y,
                msg.pose.position.z,
                roll,
                pitch,
                yaw,
            ],
            dtype=np.float32,
        )
        return ts_ns, value

    if isinstance(msg, WrenchStamped):
        value = np.asarray(
            [
                msg.wrench.force.x,
                msg.wrench.force.y,
                msg.wrench.force.z,
                msg.wrench.torque.x,
                msg.wrench.torque.y,
                msg.wrench.torque.z,
            ],
            dtype=np.float32,
        )
        return ts_ns, value

    if isinstance(msg, Bool):
        return ts_ns, bool(msg.data)

    raise TypeError(f"Unsupported message type for topic {topic}: {type(msg)}")


def read_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_value_topics(profile: dict[str, Any]) -> set[str]:
    topics: set[str] = set()
    published = profile["published"]
    for arm_sources in published["observation_state"]["sources"].values():
        topics.update(arm_sources.values())
    for arm_sources in published["action"]["sources"].values():
        topics.update(arm_sources.values())
    for image_spec in published["images"]:
        topics.add(image_spec["topic"])
    return topics


def teleop_activity_topic(profile: dict[str, Any]) -> str:
    return str(profile.get("teleop_activity", {}).get("topic", "")).strip()


def build_selected_image_specs(profile: dict[str, Any], topics_with_data: set[str]) -> list[dict[str, Any]]:
    selected_specs: list[dict[str, Any]] = []
    for image_spec in profile["published"]["images"]:
        if image_spec["required"] or image_spec["topic"] in topics_with_data:
            selected_specs.append(copy.deepcopy(image_spec))
    return selected_specs


def build_selected_depth_specs(profile: dict[str, Any], topics_with_data: set[str]) -> list[dict[str, Any]]:
    selected_specs: list[dict[str, Any]] = []
    for depth_spec in profile.get("published_depth", []):
        if depth_spec["required"] or depth_spec["topic"] in topics_with_data:
            selected_specs.append(copy.deepcopy(depth_spec))
    return selected_specs


def build_parse_topics(profile: dict[str, Any], topics_to_read: set[str], topic_types: dict[str, str], value_topics: set[str]) -> set[str]:
    parse_topics = set(value_topics)
    activity_topic = teleop_activity_topic(profile)
    if activity_topic and activity_topic in topics_to_read:
        parse_topics.add(activity_topic)
    parse_topics.update(
        topic
        for topic in topics_to_read
        if topic_types.get(topic) == "realsense2_camera_msgs/msg/Metadata"
    )
    return parse_topics


def read_topic_series(
    bag_dir: Path,
    topics_to_read: set[str],
    parse_topics: set[str],
    storage_id: str,
) -> dict[str, TopicSeries]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    message_types = {topic: get_message(topic_types[topic]) for topic in topics_to_read if topic in topic_types}
    series = {
        topic: TopicSeries(
            topic=topic,
            type_name=topic_types[topic],
            timestamps_ns=[],
            values=[],
            bag_timestamps_ns=[],
        )
        for topic in topics_to_read
        if topic in topic_types
    }

    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        if topic not in series:
            continue
        msg = deserialize_message(data, message_types[topic])
        ts_ns, value = parse_message(topic, msg, bag_timestamp_ns, parse_value=topic in parse_topics)
        series[topic].timestamps_ns.append(ts_ns)
        series[topic].values.append(value)
        series[topic].bag_timestamps_ns.append(bag_timestamp_ns)

    return series


def apply_realsense_metadata_timestamps(series: dict[str, TopicSeries]) -> None:
    image_to_metadata: dict[str, str] = {}
    for topic in series:
        if topic.endswith("/color/image_raw"):
            image_to_metadata[topic] = topic.replace("/color/image_raw", "/color/metadata")
        elif topic.endswith("/depth/image_rect_raw"):
            image_to_metadata[topic] = topic.replace("/depth/image_rect_raw", "/depth/metadata")

    for image_topic, metadata_topic in image_to_metadata.items():
        image_series = series.get(image_topic)
        metadata_series = series.get(metadata_topic)
        if not image_series or not metadata_series:
            continue
        if not metadata_series.values:
            continue

        stamp_to_toa_ns: dict[int, list[int]] = {}
        for ts_ns, value in zip(metadata_series.timestamps_ns, metadata_series.values, strict=False):
            if not isinstance(value, dict):
                continue
            time_of_arrival_ms = value.get("time_of_arrival")
            if time_of_arrival_ms is None:
                continue
            toa_ns = int(round(float(time_of_arrival_ms) * 1_000_000.0))
            stamp_to_toa_ns.setdefault(ts_ns, []).append(toa_ns)

        if not stamp_to_toa_ns:
            continue

        replaced = 0
        new_timestamps_ns: list[int] = []
        for ts_ns in image_series.timestamps_ns:
            candidates = stamp_to_toa_ns.get(ts_ns)
            if candidates:
                new_timestamps_ns.append(candidates.pop(0))
                replaced += 1
            else:
                new_timestamps_ns.append(ts_ns)

        if replaced:
            image_series.timestamps_ns = new_timestamps_ns
            image_series._ts_array = None


def ensure_series_present(series: dict[str, TopicSeries], topics: list[str]) -> None:
    missing = [topic for topic in topics if topic not in series or not series[topic].timestamps_ns]
    if missing:
        raise RuntimeError(f"Bag is missing required topics or samples: {missing}")


def build_effective_profile(
    profile: dict[str, Any],
    selected_image_specs: list[dict[str, Any]],
    selected_depth_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    effective = copy.deepcopy(profile)
    effective["published"]["images"] = selected_image_specs
    effective["published_depth"] = selected_depth_specs
    return effective


def build_features(
    effective_profile: dict[str, Any],
    image_shapes: dict[str, tuple[int, int, int]],
) -> dict[str, dict[str, Any]]:
    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (len(effective_profile["published"]["observation_state"]["names"]),),
            "names": effective_profile["published"]["observation_state"]["names"],
        },
        "action": {
            "dtype": "float32",
            "shape": (len(effective_profile["published"]["action"]["names"]),),
            "names": effective_profile["published"]["action"]["names"],
        },
    }

    for image_spec in effective_profile["published"]["images"]:
        field = image_spec["field"]
        shape = image_shapes[field]
        features[field] = {
            "dtype": "video",
            "shape": shape,
            "names": ["height", "width", "channels"],
        }
    return features


def compare_feature_specs(existing: dict[str, dict], expected: dict[str, dict]) -> None:
    existing_core = {k: v for k, v in existing.items() if not k.startswith("meta/") and k not in {"index", "episode_index", "task_index", "timestamp", "frame_index"}}
    if set(existing_core) != set(expected):
        raise RuntimeError(
            "Existing dataset features do not match this episode conversion.\n"
            f"existing={sorted(existing_core)}\nexpected={sorted(expected)}"
        )
    for key in expected:
        if (
            existing_core[key]["dtype"] != expected[key]["dtype"]
            or tuple(existing_core[key]["shape"]) != tuple(expected[key]["shape"])
            or existing_core[key].get("names") != expected[key].get("names")
        ):
            raise RuntimeError(
                f"Existing dataset feature mismatch for {key}: "
                f"existing={existing_core[key]} expected={expected[key]}"
            )


def get_or_create_dataset(
    dataset_root: Path,
    dataset_id: str,
    robot_type: str | None,
    fps: int,
    features: dict[str, dict[str, Any]],
    vcodec: str,
) -> LeRobotDataset:
    if dataset_root.exists():
        dataset = LeRobotDataset(
            repo_id=dataset_id,
            root=dataset_root,
            download_videos=False,
            vcodec=vcodec,
        )
        if dataset.fps != fps:
            raise RuntimeError(f"Existing dataset fps {dataset.fps} does not match expected fps {fps}")
        compare_feature_specs(dataset.meta.features, features)
        return dataset

    dataset_root.parent.mkdir(parents=True, exist_ok=True)
    return LeRobotDataset.create(
        repo_id=dataset_id,
        root=dataset_root,
        robot_type=robot_type,
        fps=fps,
        features=features,
        vcodec=vcodec,
    )


def ns_grid(t_start_ns: int, t_end_ns: int, fps: int) -> list[int]:
    step_ns = int(round(1_000_000_000 / fps))
    if t_end_ns < t_start_ns:
        return []
    frame_count = ((t_end_ns - t_start_ns) // step_ns) + 1
    return [t_start_ns + idx * step_ns for idx in range(frame_count)]


def summarize_errors(values_ms: list[float]) -> dict[str, float] | None:
    if not values_ms:
        return None
    arr = np.asarray(values_ms, dtype=np.float64)
    return {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
    }


def build_active_intervals(
    activity_series: TopicSeries,
    *,
    active_value: bool,
    clamp_start_ns: int,
    clamp_end_ns: int,
) -> list[ActiveInterval]:
    if clamp_end_ns < clamp_start_ns or not activity_series.timestamps_ns:
        return []

    intervals: list[ActiveInterval] = []
    timestamps = activity_series.timestamps_ns
    values = activity_series.values
    current_active = bool(values[0]) == active_value
    current_start_ns = timestamps[0] if current_active else None

    for ts_ns, value in zip(timestamps[1:], values[1:], strict=False):
        next_active = bool(value) == active_value
        if current_active and not next_active:
            if current_start_ns is not None:
                interval_start_ns = max(current_start_ns, clamp_start_ns)
                interval_end_ns = min(ts_ns - 1, clamp_end_ns)
                if interval_end_ns >= interval_start_ns:
                    intervals.append(ActiveInterval(start_ns=interval_start_ns, end_ns=interval_end_ns))
            current_start_ns = None
        elif not current_active and next_active:
            current_start_ns = ts_ns
        current_active = next_active

    if current_active and current_start_ns is not None:
        interval_start_ns = max(current_start_ns, clamp_start_ns)
        interval_end_ns = clamp_end_ns
        if interval_end_ns >= interval_start_ns:
            intervals.append(ActiveInterval(start_ns=interval_start_ns, end_ns=interval_end_ns))

    return intervals


def filter_grid_to_intervals(grid: list[int], intervals: list[ActiveInterval]) -> list[int]:
    if not intervals:
        return []
    filtered: list[int] = []
    interval_index = 0
    for t_ns in grid:
        while interval_index < len(intervals) and t_ns > intervals[interval_index].end_ns:
            interval_index += 1
        if interval_index >= len(intervals):
            break
        interval = intervals[interval_index]
        if interval.start_ns <= t_ns <= interval.end_ns:
            filtered.append(t_ns)
    return filtered


def activity_interval_diagnostics(intervals: list[ActiveInterval]) -> dict[str, Any]:
    active_duration_ns = sum(interval.end_ns - interval.start_ns for interval in intervals)
    return {
        "activity_interval_count": len(intervals),
        "activity_intervals_ns": [
            {"start_ns": interval.start_ns, "end_ns": interval.end_ns}
            for interval in intervals
        ],
        "active_duration_s": float(active_duration_ns / 1_000_000_000.0),
    }


def align_episode(
    series: dict[str, TopicSeries],
    profile: dict[str, Any],
    selected_image_specs: list[dict[str, Any]],
    selected_depth_specs: list[dict[str, Any]],
    task_name: str,
    language_instruction: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[DepthSelection]], dict[str, Any], str]:
    arm_order = profile["notes"]["arm_order"]
    fps = int(profile["dataset"]["fps"])
    published = profile["published"]
    state_age_ns = int(round(float(published["observation_state"].get("max_age_ms", 50)) * 1_000_000.0))
    action_age_ns = int(round(float(published["action"].get("max_age_ms", 50)) * 1_000_000.0))
    activity_topic = teleop_activity_topic(profile)
    activity_active_value = bool(profile.get("teleop_activity", {}).get("active_value", True))

    state_sources = published["observation_state"]["sources"]
    action_sources = published["action"]["sources"]
    expected_state_dim = len(published["observation_state"]["names"])
    expected_action_dim = len(published["action"]["names"])

    required_topics: list[str] = []
    for arm in arm_order:
        required_topics.extend(state_sources[arm].values())
        required_topics.extend(action_sources[arm].values())
    required_topics.extend(spec["topic"] for spec in selected_image_specs)
    required_topics.extend(spec["topic"] for spec in selected_depth_specs)
    if activity_topic:
        required_topics.append(activity_topic)

    ensure_series_present(series, required_topics)

    t_start_ns = max(series[topic].first_ts() for topic in required_topics)
    t_end_ns = min(series[topic].last_ts() for topic in required_topics)
    full_grid = ns_grid(t_start_ns, t_end_ns, fps)
    activity_intervals: list[ActiveInterval] = []
    activity_mode = "disabled"
    if activity_topic and activity_topic in series and series[activity_topic].timestamps_ns:
        activity_intervals = build_active_intervals(
            series[activity_topic],
            active_value=activity_active_value,
            clamp_start_ns=t_start_ns,
            clamp_end_ns=t_end_ns,
        )
        activity_mode = "filtered_by_enable"
        grid = filter_grid_to_intervals(full_grid, activity_intervals)
    else:
        raise RuntimeError("Teleop activity topic is required for conversion but was missing or empty.")
    if not grid:
        raise RuntimeError(
            f"No valid {fps}Hz frame grid can be formed for interval [{t_start_ns}, {t_end_ns}] "
            f"after teleop-activity filtering."
        )

    frames: list[dict[str, Any]] = []
    failures: list[AlignmentFailure] = []
    state_alignment: dict[str, list[float]] = {
        topic: []
        for arm in arm_order
        for topic in state_sources[arm].values()
    }
    action_alignment: dict[str, list[float]] = {
        topic: []
        for arm in arm_order
        for topic in action_sources[arm].values()
    }
    image_alignment: dict[str, list[float]] = {spec["field"]: [] for spec in selected_image_specs}
    depth_alignment: dict[str, list[float]] = {spec["field"]: [] for spec in selected_depth_specs}
    depth_selections: dict[str, list[DepthSelection]] = {spec["field"]: [] for spec in selected_depth_specs}

    state_topic_order = []
    for arm in arm_order:
        state_topic_order.extend(
            [
                state_sources[arm]["joint_state"],
                state_sources[arm]["eef_pose"],
                state_sources[arm]["gripper_state"],
                state_sources[arm]["tcp_wrench"],
            ]
        )

    action_topic_order = []
    for arm in arm_order:
        action_topic_order.extend(
            [
                action_sources[arm]["cmd_joint_state"],
                action_sources[arm]["cmd_gripper_state"],
            ]
        )

    for frame_index, t_ns in enumerate(grid):
        state_parts: list[np.ndarray] = []
        action_parts: list[np.ndarray] = []
        image_values: dict[str, np.ndarray] = {}
        depth_frame_selections: list[DepthSelection] = []
        failure_reason: str | None = None

        for topic in state_topic_order:
            result = series[topic].latest_before(t_ns)
            if result is None:
                failure_reason = f"missing latest-before state sample for {topic}"
                break
            value, age_ns = result
            if age_ns > state_age_ns:
                failure_reason = f"state sample too old for {topic}: {age_ns / 1e6:.2f} ms"
                break
            state_alignment[topic].append(age_ns / 1e6)
            state_parts.append(value)

        if failure_reason is None:
            for topic in action_topic_order:
                result = series[topic].latest_before(t_ns)
                if result is None:
                    failure_reason = f"missing latest-before action sample for {topic}"
                    break
                value, age_ns = result
                if age_ns > action_age_ns:
                    failure_reason = f"action sample too old for {topic}: {age_ns / 1e6:.2f} ms"
                    break
                action_alignment[topic].append(age_ns / 1e6)
                action_parts.append(value)

        if failure_reason is None:
            for image_spec in selected_image_specs:
                topic = image_spec["topic"]
                result = series[topic].nearest(t_ns)
                if result is None:
                    failure_reason = f"missing nearest image sample for {topic}"
                    break
                value, skew_ns = result
                image_skew_ns = int(round(float(image_spec.get("max_skew_ms", 25)) * 1_000_000.0))
                if skew_ns > image_skew_ns:
                    failure_reason = f"image sample too far from grid for {topic}: {skew_ns / 1e6:.2f} ms"
                    break
                image_alignment[image_spec["field"]].append(skew_ns / 1e6)
                image_values[image_spec["field"]] = value

        if failure_reason is None:
            for depth_spec in selected_depth_specs:
                topic = depth_spec["topic"]
                result = series[topic].nearest_index(t_ns)
                if result is None:
                    failure_reason = f"missing nearest depth sample for {topic}"
                    break
                sample_index, skew_ns = result
                depth_skew_ns = int(round(float(depth_spec.get("max_skew_ms", 25)) * 1_000_000.0))
                if skew_ns > depth_skew_ns:
                    failure_reason = f"depth sample too far from grid for {topic}: {skew_ns / 1e6:.2f} ms"
                    break
                depth_alignment[depth_spec["field"]].append(skew_ns / 1e6)
                depth_frame_selections.append(
                    DepthSelection(
                        field=depth_spec["field"],
                        topic=topic,
                        sample_index=sample_index,
                        frame_index=len(frames),
                        timestamp_ns=t_ns,
                        skew_ms=skew_ns / 1e6,
                    )
                )

        if failure_reason is not None:
            failures.append(AlignmentFailure(frame_index=frame_index, timestamp_ns=t_ns, reason=failure_reason))
            continue

        state_vector = np.concatenate(state_parts).astype(np.float32)
        action_vector = np.concatenate(action_parts).astype(np.float32)
        if state_vector.shape != (expected_state_dim,):
            raise RuntimeError(
                f"State vector shape mismatch: got {state_vector.shape}, expected {(expected_state_dim,)}"
            )
        if action_vector.shape != (expected_action_dim,):
            raise RuntimeError(
                f"Action vector shape mismatch: got {action_vector.shape}, expected {(expected_action_dim,)}"
            )
        frame = {
            "observation.state": state_vector,
            "action": action_vector,
            "task": language_instruction or task_name,
            **image_values,
        }
        frames.append(frame)
        for selection in depth_frame_selections:
            depth_selections[selection.field].append(selection)

    if not frames:
        raise RuntimeError("No valid published frames remained after alignment.")

    if failures:
        first_invalid = failures[0].frame_index
        contiguous_tail = [failure.frame_index for failure in failures] == list(range(first_invalid, len(grid)))
        if not contiguous_tail:
            raise RuntimeError(
                "Mid-episode alignment failure encountered.\n"
                f"first_failure={failures[0].__dict__}\n"
                f"num_failures={len(failures)}"
            )
        frames = frames[:first_invalid]
        if not frames:
            raise RuntimeError("All frames were truncated by tail-failure handling.")
        summary_status = "truncated_tail"
    else:
        summary_status = "pass"

    diagnostics = {
        "usable_interval_ns": {
            "t_start_ns": t_start_ns,
            "t_end_ns": t_end_ns,
        },
        "activity_filter": {
            "mode": activity_mode,
            "topic": activity_topic or None,
            "active_value": activity_active_value,
            "grid_frame_count_before_filter": len(full_grid),
            "grid_frame_count_after_filter": len(grid),
            "inactive_removed_frame_count": len(full_grid) - len(grid),
            "inactive_removed_duration_s": float((len(full_grid) - len(grid)) / fps) if fps > 0 else 0.0,
            **activity_interval_diagnostics(activity_intervals),
        },
        "published_frame_count": len(frames),
        "invalid_frame_count": len(failures),
        "alignment_policy": {
            "state_max_age_ms": state_age_ns / 1_000_000.0,
            "action_max_age_ms": action_age_ns / 1_000_000.0,
            "image_max_skew_ms": {
                spec["field"]: float(spec.get("max_skew_ms", 25))
                for spec in selected_image_specs
            },
            "depth_max_skew_ms": {
                spec["field"]: float(spec.get("max_skew_ms", 25))
                for spec in selected_depth_specs
            },
        },
        "alignment_error_ms": {
            "state_topics": {topic: summarize_errors(values) for topic, values in state_alignment.items()},
            "action_topics": {topic: summarize_errors(values) for topic, values in action_alignment.items()},
            "image_fields": {field: summarize_errors(values) for field, values in image_alignment.items()},
            "depth_fields": {field: summarize_errors(values) for field, values in depth_alignment.items()},
        },
        "action_hold_diagnostics": {
            "topics": {
                topic: {
                    "max_action_age_ms": max(values) if values else 0.0,
                    "num_frames_over_50ms": int(sum(1 for value in values if value > 50.0)),
                    "num_frames_over_100ms": int(sum(1 for value in values if value > 100.0)),
                }
                for topic, values in action_alignment.items()
            }
        },
        "failures": [failure.__dict__ for failure in failures[:25]],
    }
    return frames, depth_selections, diagnostics, summary_status


def image_shapes_from_frames(frames: list[dict[str, Any]], image_fields: list[str]) -> dict[str, tuple[int, int, int]]:
    shapes: dict[str, tuple[int, int, int]] = {}
    first_frame = frames[0]
    for field in image_fields:
        value = first_frame[field]
        if not isinstance(value, np.ndarray) or value.ndim != 3:
            raise RuntimeError(f"Image field {field} is not a 3D numpy array.")
        shapes[field] = tuple(int(dim) for dim in value.shape)
    return shapes


def extract_depth_arrays(
    bag_dir: Path,
    storage_id: str,
    depth_selections: dict[str, list[DepthSelection]],
) -> dict[str, list[np.ndarray]]:
    topic_to_requested_indices: dict[str, set[int]] = {}
    for selections in depth_selections.values():
        for selection in selections:
            topic_to_requested_indices.setdefault(selection.topic, set()).add(selection.sample_index)

    if not topic_to_requested_indices:
        return {field: [] for field in depth_selections}

    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    message_types = {
        topic: get_message(topic_types[topic]) for topic in topic_to_requested_indices if topic in topic_types
    }

    topic_indices = {topic: 0 for topic in topic_to_requested_indices}
    extracted: dict[tuple[str, int], np.ndarray] = {}

    while reader.has_next():
        topic, data, _ = reader.read_next()
        if topic not in topic_to_requested_indices:
            continue
        topic_index = topic_indices[topic]
        topic_indices[topic] += 1
        if topic_index not in topic_to_requested_indices[topic]:
            continue
        msg = deserialize_message(data, message_types[topic])
        extracted[(topic, topic_index)] = decode_image_to_depth(msg)

    rows_by_field: dict[str, list[np.ndarray]] = {}
    for field, selections in depth_selections.items():
        rows: list[np.ndarray] = []
        for selection in selections:
            key = (selection.topic, selection.sample_index)
            if key not in extracted:
                raise RuntimeError(f"Missing extracted depth sample for {selection.topic} index={selection.sample_index}")
            rows.append(extracted[key])
        rows_by_field[field] = rows
    return rows_by_field


def write_depth_sidecar(
    dataset_root: Path,
    dataset_id: str,
    dataset_episode_index: int,
    fps: int,
    depth_specs: list[dict[str, Any]],
    depth_selections: dict[str, list[DepthSelection]],
    depth_arrays: dict[str, list[np.ndarray]],
    depth_preview_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    depth_root = dataset_root / "depth"
    depth_root.mkdir(parents=True, exist_ok=True)

    field_info: dict[str, Any] = {}
    episode_indices_present: set[int] = set()

    for depth_spec in depth_specs:
        field = depth_spec["field"]
        selections = depth_selections.get(field, [])
        arrays = depth_arrays.get(field, [])
        if len(selections) != len(arrays):
            raise RuntimeError(
                f"Depth selection/data length mismatch for {field}: selections={len(selections)} arrays={len(arrays)}"
            )

        field_dir = depth_root / field / "chunk-000"
        field_dir.mkdir(parents=True, exist_ok=True)
        file_path = field_dir / f"file-{dataset_episode_index:03d}.parquet"
        if file_path.exists():
            raise RuntimeError(f"Depth sidecar already exists for {field} episode_index={dataset_episode_index}: {file_path}")

        rows = []
        for selection, depth_array in zip(selections, arrays, strict=False):
            png_bytes = encode_depth_png16(depth_array)
            rows.append(
                {
                    "episode_index": int(dataset_episode_index),
                    "frame_index": int(selection.frame_index),
                    "timestamp": float(selection.timestamp_ns / 1_000_000_000.0),
                    "png16_bytes": png_bytes,
                    "height": int(depth_array.shape[0]),
                    "width": int(depth_array.shape[1]),
                    "source_topic": selection.topic,
                }
            )

        table = pa.Table.from_pylist(rows)
        pq.write_table(table, file_path)
        episode_indices_present.add(dataset_episode_index)
        field_info[field] = {
            "source_topic": depth_spec["topic"],
            "unit": str(depth_spec.get("unit", "raw_uint16")),
            "max_skew_ms": float(depth_spec.get("max_skew_ms", 25)),
            "path": str(file_path.relative_to(dataset_root)),
            "row_count": len(rows),
        }

    info_path = dataset_root / "meta" / "depth_info.json"
    if info_path.is_file():
        with info_path.open("r", encoding="utf-8") as handle:
            depth_info = json.load(handle)
    else:
        depth_info = {
            "dataset_id": dataset_id,
            "encoding": "png16_gray",
            "unit": "raw_uint16",
            "chunking": {
                "mode": "per_episode_file",
                "chunk": "chunk-000",
                "filename_pattern": "file-{episode_index:03d}.parquet",
            },
            "episode_indices_present": [],
            "depth_fields": {},
        }

    depth_info["dataset_id"] = dataset_id
    depth_info["alignment_policy"] = {
        "grid_fps": int(fps),
        "selector": "nearest",
    }
    if depth_preview_summary:
        depth_info["preview_videos"] = {
            "encoding": "mp4_h264_rgb8",
            "chunking": {
                "mode": "per_episode_file",
                "chunk": "chunk-000",
                "filename_pattern": "file-{episode_index:03d}.mp4",
            },
            "colorizer": {
                "source": "librealsense::colorizer",
                "visual_preset": "Dynamic",
                "color_scheme": "Jet",
                "histogram_equalization": True,
                "zero_depth": "black",
            },
        }
    existing_indices = set(depth_info.get("episode_indices_present", []))
    existing_indices.update(episode_indices_present)
    depth_info["episode_indices_present"] = sorted(existing_indices)
    for field, info in field_info.items():
        depth_info.setdefault("depth_fields", {})[field] = {
            "source_topic": info["source_topic"],
            "unit": info["unit"],
            "max_skew_ms": info["max_skew_ms"],
        }

    write_json(info_path, depth_info)

    return {
        "root": str(depth_root),
        "info_path": str(info_path),
        "fields": field_info,
    }


def write_depth_preview_videos(
    dataset_root: Path,
    dataset_episode_index: int,
    fps: int,
    depth_specs: list[dict[str, Any]],
    depth_arrays: dict[str, list[np.ndarray]],
) -> dict[str, Any]:
    preview_root = dataset_root / "depth_preview"
    preview_root.mkdir(parents=True, exist_ok=True)

    field_info: dict[str, Any] = {}

    for depth_spec in depth_specs:
        field = depth_spec["field"]
        arrays = depth_arrays.get(field, [])
        if not arrays:
            continue

        field_dir = preview_root / field / "chunk-000"
        field_dir.mkdir(parents=True, exist_ok=True)
        file_path = field_dir / f"file-{dataset_episode_index:03d}.mp4"
        if file_path.exists():
            raise RuntimeError(
                f"Depth preview video already exists for {field} episode_index={dataset_episode_index}: {file_path}"
            )

        writer = imageio.get_writer(
            file_path,
            fps=fps,
            codec="libx264",
            format="FFMPEG",
            macro_block_size=None,
            ffmpeg_log_level="error",
            ffmpeg_params=["-pix_fmt", "yuv420p"],
        )
        try:
            for depth_array in arrays:
                writer.append_data(colorize_depth_realsense_preview(depth_array))
        finally:
            writer.close()

        field_info[field] = {
            "source_topic": depth_spec["topic"],
            "path": str(file_path.relative_to(dataset_root)),
            "frame_count": len(arrays),
        }

    return {
        "root": str(preview_root),
        "fields": field_info,
    }


def write_conversion_artifacts(
    artifact_dir: Path,
    diagnostics: dict[str, Any],
    effective_profile: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifact_dir / "diagnostics.json", diagnostics)
    write_json(artifact_dir / "conversion_summary.json", summary)
    with (artifact_dir / "effective_profile.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(effective_profile, handle, sort_keys=False)


def copy_source_snapshot(
    dataset_root: Path,
    episode_dir: Path,
    episode_id: str,
) -> dict[str, str | None]:
    source_root = dataset_root / "meta" / "spark_source" / episode_id
    source_root.mkdir(parents=True, exist_ok=True)

    manifest_src = episode_dir / "episode_manifest.json"
    manifest_dst = source_root / "episode_manifest.json"
    shutil.copy2(manifest_src, manifest_dst)

    notes_src = episode_dir / "notes.md"
    notes_dst = source_root / "notes.md"
    notes_path: str | None = None
    if notes_src.is_file():
        shutil.copy2(notes_src, notes_dst)
        notes_path = str(notes_dst.relative_to(dataset_root))

    return {
        "root": str(source_root.relative_to(dataset_root)),
        "episode_manifest_path": str(manifest_dst.relative_to(dataset_root)),
        "notes_path": notes_path,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--profile", default="")
    parser.add_argument("--published-dataset-id", default="")
    parser.add_argument("--published-root", type=Path, default=REPO_ROOT / "published")
    parser.add_argument("--vcodec", default="auto")
    parser.add_argument("--skip-validate-load", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    episode_dir = args.episode_dir.resolve()
    manifest_path = episode_dir / "episode_manifest.json"
    bag_dir = episode_dir / "bag"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    if not bag_dir.is_dir():
        raise FileNotFoundError(f"Missing bag directory: {bag_dir}")

    manifest = read_manifest(manifest_path)
    profile_ref = args.profile or manifest_profile_name(manifest)
    profile = load_profile(profile_ref)
    if manifest_profile_name(manifest) != profile["profile_name"]:
        raise RuntimeError(
            f"Manifest profile={manifest_profile_name(manifest)} does not match profile {profile['profile_name']}"
        )
    manifest_arms = manifest_active_arms(manifest)
    normalized_manifest_arms = normalize_active_arms(manifest_arms) if manifest_arms else []
    if manifest_arms:
        normalized_profile_arms = profile_required_arms(profile)
        if normalized_profile_arms and normalized_manifest_arms != normalized_profile_arms:
            raise RuntimeError(
                f"Manifest active_arms {normalized_manifest_arms} do not match profile arms {normalized_profile_arms}"
            )

    recorded_sensor_keys = [
        str(sensor.get("sensor_key", "")).strip()
        for sensor in manifest_sensors(manifest)
        if isinstance(sensor, dict)
    ]
    effective_profile = effective_profile_for_session(profile, normalized_manifest_arms, recorded_sensor_keys)

    topic_types = manifest_topic_types(manifest)
    all_topics_to_read = set(topic_types)
    value_topics = build_value_topics(effective_profile) & all_topics_to_read
    parse_topics = build_parse_topics(effective_profile, all_topics_to_read, topic_types, value_topics)
    bag_storage_id = detect_bag_storage_id(bag_dir)
    series = read_topic_series(bag_dir, all_topics_to_read, parse_topics, storage_id=bag_storage_id)
    apply_realsense_metadata_timestamps(series)
    topics_with_data = {topic for topic, values in series.items() if values.timestamps_ns}

    selected_image_specs = build_selected_image_specs(effective_profile, topics_with_data)
    selected_depth_specs = build_selected_depth_specs(effective_profile, topics_with_data)
    effective_profile = build_effective_profile(effective_profile, selected_image_specs, selected_depth_specs)

    frames, depth_selections, alignment_diagnostics, summary_status = align_episode(
        series=series,
        profile=effective_profile,
        selected_image_specs=selected_image_specs,
        selected_depth_specs=selected_depth_specs,
        task_name=manifest_task_name(manifest),
        language_instruction=manifest_language_instruction(manifest),
    )

    image_fields = [spec["field"] for spec in selected_image_specs]
    image_shapes = image_shapes_from_frames(frames, image_fields)
    features = build_features(effective_profile, image_shapes)

    dataset_id = args.published_dataset_id
    if not dataset_id:
        raise RuntimeError("Conversion requires --published-dataset-id.")
    dataset_root = args.published_root / dataset_id
    artifact_dir = dataset_root / "meta" / "spark_conversion" / manifest_episode_id(manifest)
    if artifact_dir.exists():
        raise RuntimeError(f"Conversion artifacts already exist for {manifest_episode_id(manifest)} at {artifact_dir}")

    dataset = get_or_create_dataset(
        dataset_root=dataset_root,
        dataset_id=dataset_id,
        robot_type=manifest_robot_id(manifest),
        fps=int(effective_profile["dataset"]["fps"]),
        features=features,
        vcodec=args.vcodec,
    )
    dataset_episode_index = dataset.meta.total_episodes

    try:
        for frame in frames:
            dataset.add_frame(frame)
        dataset.save_episode()
        dataset.finalize()
    finally:
        dataset.finalize()

    if not args.skip_validate_load:
        reloaded = LeRobotDataset(
            repo_id=dataset_id,
            root=dataset_root,
            download_videos=False,
        )
        reloaded.finalize()

    depth_sidecar_summary: dict[str, Any] | None = None
    depth_preview_summary: dict[str, Any] | None = None
    if selected_depth_specs:
        depth_arrays = extract_depth_arrays(
            bag_dir=bag_dir,
            storage_id=bag_storage_id,
            depth_selections=depth_selections,
        )
        depth_preview_summary = write_depth_preview_videos(
            dataset_root=dataset_root,
            dataset_episode_index=dataset_episode_index,
            fps=int(effective_profile["dataset"]["fps"]),
            depth_specs=selected_depth_specs,
            depth_arrays=depth_arrays,
        )
        depth_sidecar_summary = write_depth_sidecar(
            dataset_root=dataset_root,
            dataset_id=dataset_id,
            dataset_episode_index=dataset_episode_index,
            fps=int(effective_profile["dataset"]["fps"]),
            depth_specs=selected_depth_specs,
            depth_selections=depth_selections,
            depth_arrays=depth_arrays,
            depth_preview_summary=depth_preview_summary,
        )

    source_snapshot = copy_source_snapshot(
        dataset_root=dataset_root,
        episode_dir=episode_dir,
        episode_id=manifest_episode_id(manifest),
    )

    diagnostics = {
        "episode_id": manifest_episode_id(manifest),
        "manifest_dataset_id": manifest_dataset_id(manifest),
        "dataset_id": dataset_id,
        "dataset_root": str(dataset_root),
        "dataset_episode_index": dataset_episode_index,
        "clock_policy": manifest_clock_policy(manifest),
        "bag_storage_id": bag_storage_id,
        "summary_status": summary_status,
        "topic_diagnostics": {topic: series[topic].diagnostics() for topic in sorted(series)},
        "depth_sidecar": depth_sidecar_summary,
        "depth_preview": depth_preview_summary,
        "source_snapshot": source_snapshot,
        **alignment_diagnostics,
    }
    summary = {
        "episode_id": manifest_episode_id(manifest),
        "manifest_dataset_id": manifest_dataset_id(manifest),
        "dataset_id": dataset_id,
        "dataset_root": str(dataset_root),
        "dataset_episode_index": dataset_episode_index,
        "bag_storage_id": bag_storage_id,
        "published_frame_count": len(frames),
        "status": summary_status,
        "selected_image_fields": image_fields,
        "selected_depth_fields": [spec["field"] for spec in selected_depth_specs],
        "depth_sidecar_root": depth_sidecar_summary["root"] if depth_sidecar_summary else None,
        "depth_preview_root": depth_preview_summary["root"] if depth_preview_summary else None,
        "source_snapshot": source_snapshot,
    }
    write_conversion_artifacts(artifact_dir, diagnostics, effective_profile, summary)

    print(f"Converted {manifest_episode_id(manifest)} -> {dataset_root}")
    print(f"episode_index={dataset_episode_index}")
    print(f"status={summary_status}")
    print(f"published_frames={len(frames)}")
    print(f"artifacts={artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
