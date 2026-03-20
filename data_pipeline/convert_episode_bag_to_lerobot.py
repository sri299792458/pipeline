#!/usr/bin/env python3

"""Convert one raw V1 rosbag episode into the published LeRobot dataset."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rosbag2_py
import yaml
from geometry_msgs.msg import PoseStamped, WrenchStamped
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from sensor_msgs.msg import Image, JointState

try:
    from realsense2_camera_msgs.msg import Metadata
except ImportError:
    Metadata = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import DEFAULT_PROFILE_PATH, load_profile, write_json  # noqa: E402
from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402


STATE_AGE_NS = 50_000_000
ACTION_AGE_NS = 50_000_000
IMAGE_SKEW_NS = 25_000_000


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


def build_selected_image_specs(profile: dict[str, Any], topics_with_data: set[str]) -> list[dict[str, Any]]:
    selected_specs: list[dict[str, Any]] = []
    for image_spec in profile["published"]["images"]:
        if image_spec["required"] or image_spec["topic"] in topics_with_data:
            selected_specs.append(copy.deepcopy(image_spec))
    return selected_specs


def build_parse_topics(topics_to_read: set[str], topic_types: dict[str, str], value_topics: set[str]) -> set[str]:
    parse_topics = set(value_topics)
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
) -> dict[str, TopicSeries]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id="sqlite3")
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
    image_to_metadata = {
        "/spark/cameras/wrist/color/image_raw": "/spark/cameras/wrist/color/metadata",
        "/spark/cameras/wrist/depth/image_rect_raw": "/spark/cameras/wrist/depth/metadata",
        "/spark/cameras/scene/color/image_raw": "/spark/cameras/scene/color/metadata",
        "/spark/cameras/scene/depth/image_rect_raw": "/spark/cameras/scene/depth/metadata",
    }

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


def build_effective_profile(profile: dict[str, Any], selected_image_specs: list[dict[str, Any]]) -> dict[str, Any]:
    effective = copy.deepcopy(profile)
    effective["published"]["images"] = selected_image_specs
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
    robot_type: str,
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


def align_episode(
    series: dict[str, TopicSeries],
    profile: dict[str, Any],
    selected_image_specs: list[dict[str, Any]],
    task_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    arm_order = profile["notes"]["arm_order"]
    fps = int(profile["dataset"]["fps"])

    state_sources = profile["published"]["observation_state"]["sources"]
    action_sources = profile["published"]["action"]["sources"]
    expected_state_dim = len(profile["published"]["observation_state"]["names"])
    expected_action_dim = len(profile["published"]["action"]["names"])

    required_topics: list[str] = []
    for arm in arm_order:
        required_topics.extend(state_sources[arm].values())
        required_topics.extend(action_sources[arm].values())
    required_topics.extend(spec["topic"] for spec in selected_image_specs)

    ensure_series_present(series, required_topics)

    t_start_ns = max(series[topic].first_ts() for topic in required_topics)
    t_end_ns = min(series[topic].last_ts() for topic in required_topics)
    grid = ns_grid(t_start_ns, t_end_ns, fps)
    if not grid:
        raise RuntimeError(f"No valid 20Hz frame grid can be formed for interval [{t_start_ns}, {t_end_ns}]")

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
        failure_reason: str | None = None

        for topic in state_topic_order:
            result = series[topic].latest_before(t_ns)
            if result is None:
                failure_reason = f"missing latest-before state sample for {topic}"
                break
            value, age_ns = result
            if age_ns > STATE_AGE_NS:
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
                if age_ns > ACTION_AGE_NS:
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
                if skew_ns > IMAGE_SKEW_NS:
                    failure_reason = f"image sample too far from grid for {topic}: {skew_ns / 1e6:.2f} ms"
                    break
                image_alignment[image_spec["field"]].append(skew_ns / 1e6)
                image_values[image_spec["field"]] = value

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
            "task": task_name,
            **image_values,
        }
        frames.append(frame)

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
        "published_frame_count": len(frames),
        "invalid_frame_count": len(failures),
        "alignment_error_ms": {
            "state_topics": {topic: summarize_errors(values) for topic, values in state_alignment.items()},
            "action_topics": {topic: summarize_errors(values) for topic, values in action_alignment.items()},
            "image_fields": {field: summarize_errors(values) for field, values in image_alignment.items()},
        },
        "failures": [failure.__dict__ for failure in failures[:25]],
    }
    return frames, diagnostics, summary_status


def image_shapes_from_frames(frames: list[dict[str, Any]], image_fields: list[str]) -> dict[str, tuple[int, int, int]]:
    shapes: dict[str, tuple[int, int, int]] = {}
    first_frame = frames[0]
    for field in image_fields:
        value = first_frame[field]
        if not isinstance(value, np.ndarray) or value.ndim != 3:
            raise RuntimeError(f"Image field {field} is not a 3D numpy array.")
        shapes[field] = tuple(int(dim) for dim in value.shape)
    return shapes


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
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
    profile = load_profile(args.profile)
    if manifest["mapping_profile"] != profile["profile_name"]:
        raise RuntimeError(
            f"Manifest mapping_profile={manifest['mapping_profile']} does not match profile {profile['profile_name']}"
        )

    all_topics_to_read = set(manifest["topics"])
    topic_types = manifest.get("topic_types", {})
    value_topics = build_value_topics(profile) & all_topics_to_read
    parse_topics = build_parse_topics(all_topics_to_read, topic_types, value_topics)
    series = read_topic_series(bag_dir, all_topics_to_read, parse_topics)
    apply_realsense_metadata_timestamps(series)
    topics_with_data = {topic for topic, values in series.items() if values.timestamps_ns}

    selected_image_specs = build_selected_image_specs(profile, topics_with_data)
    effective_profile = build_effective_profile(profile, selected_image_specs)

    frames, alignment_diagnostics, summary_status = align_episode(
        series=series,
        profile=effective_profile,
        selected_image_specs=selected_image_specs,
        task_name=manifest["task_name"],
    )

    image_fields = [spec["field"] for spec in selected_image_specs]
    image_shapes = image_shapes_from_frames(frames, image_fields)
    features = build_features(effective_profile, image_shapes)

    dataset_id = manifest["dataset_id"]
    dataset_root = args.published_root / dataset_id
    artifact_dir = dataset_root / "meta" / "spark_conversion" / manifest["episode_id"]
    if artifact_dir.exists():
        raise RuntimeError(f"Conversion artifacts already exist for {manifest['episode_id']} at {artifact_dir}")

    dataset = get_or_create_dataset(
        dataset_root=dataset_root,
        dataset_id=dataset_id,
        robot_type=manifest["robot_id"],
        fps=int(profile["dataset"]["fps"]),
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

    diagnostics = {
        "episode_id": manifest["episode_id"],
        "dataset_id": dataset_id,
        "dataset_root": str(dataset_root),
        "dataset_episode_index": dataset_episode_index,
        "clock_policy": manifest["clock_policy"],
        "summary_status": summary_status,
        "topic_diagnostics": {topic: series[topic].diagnostics() for topic in sorted(series)},
        **alignment_diagnostics,
    }
    summary = {
        "episode_id": manifest["episode_id"],
        "dataset_id": dataset_id,
        "dataset_root": str(dataset_root),
        "dataset_episode_index": dataset_episode_index,
        "published_frame_count": len(frames),
        "status": summary_status,
        "selected_image_fields": image_fields,
    }
    write_conversion_artifacts(artifact_dir, diagnostics, effective_profile, summary)

    print(f"Converted {manifest['episode_id']} -> {dataset_root}")
    print(f"episode_index={dataset_episode_index}")
    print(f"status={summary_status}")
    print(f"published_frames={len(frames)}")
    print(f"artifacts={artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
