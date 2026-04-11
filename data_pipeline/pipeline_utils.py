#!/usr/bin/python3

"""Shared helpers for the V2 data pipeline scripts."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = REPO_ROOT / "data_pipeline" / "configs"
DEFAULT_PROFILE_PATH = REPO_ROOT / "data_pipeline" / "configs" / "multisensor_20hz.yaml"
DEFAULT_RAW_EPISODES_DIR = REPO_ROOT / "raw_episodes"
DEFAULT_CALIBRATION_RESULTS_PATH = CONFIGS_DIR / "calibration.local.json"
DEFAULT_BAG_STORAGE_ID = "mcap"
DEFAULT_BAG_STORAGE_PRESET_PROFILE = ""
ARM_ORDER = ("lightning", "thunder")
PROFILE_NAME_TO_PATH = {
    "multisensor_20hz": CONFIGS_DIR / "multisensor_20hz.yaml",
}

_TOPIC_TYPE_PATTERN = re.compile(r"^(?P<topic>/\S+)\s+\[(?P<type>[^\]]+)\]\s*$")
_CAMERA_SENSOR_KEY_PATTERN = re.compile(r"^/spark/cameras/(?P<attachment>lightning|thunder|world)/(?P<slot>[a-z0-9_]+)$")
_TACTILE_SENSOR_KEY_PATTERN = re.compile(r"^/spark/tactile/(?P<arm>lightning|thunder)/(?P<finger>finger_left|finger_right)$")
_CAMERA_TOPIC_PATTERN = re.compile(
    r"^/spark/cameras/(?P<attachment>lightning|thunder|world)/(?P<slot>[a-z0-9_]+)/"
    r"(?P<suffix>color/image_raw|depth/image_rect_raw|color/metadata|depth/metadata)$"
)
_TACTILE_TOPIC_PATTERN = re.compile(
    r"^/spark/tactile/(?P<arm>lightning|thunder)/(?P<finger>finger_left|finger_right)/"
    r"(?P<suffix>color/image_raw)$"
)
_STATE_SOURCE_COUNTS = (
    ("joint_state", 6),
    ("eef_pose", 6),
    ("gripper_state", 1),
    ("tcp_wrench", 6),
)
_ACTION_SOURCE_COUNTS = (
    ("cmd_joint_state", 6),
    ("cmd_gripper_state", 1),
)
_STATE_FIELD_TEMPLATES = {
    "joint_state": [f"joint_pos_{index}" for index in range(1, 7)],
    "eef_pose": ["eef_x", "eef_y", "eef_z", "eef_rx", "eef_ry", "eef_rz"],
    "gripper_state": ["gripper_position"],
    "tcp_wrench": ["ft_fx", "ft_fy", "ft_fz", "ft_tx", "ft_ty", "ft_tz"],
}
_ACTION_FIELD_TEMPLATES = {
    "cmd_joint_state": [f"cmd_joint_{index}" for index in range(1, 7)],
    "cmd_gripper_state": ["cmd_gripper"],
}


def camera_path_parts_for_sensor_key(sensor_key: str) -> tuple[str, str] | None:
    match = _CAMERA_SENSOR_KEY_PATTERN.fullmatch(str(sensor_key).strip())
    if not match:
        return None
    return match.group("attachment"), match.group("slot")


def tactile_path_parts_for_sensor_key(sensor_key: str) -> tuple[str, str] | None:
    match = _TACTILE_SENSOR_KEY_PATTERN.fullmatch(str(sensor_key).strip())
    if not match:
        return None
    return match.group("arm"), match.group("finger")


def canonical_sensor_key(value: str) -> str:
    return str(value).strip()


def camera_topic_prefix_for_sensor_key(sensor_key: str) -> str | None:
    parts = camera_path_parts_for_sensor_key(sensor_key)
    if parts is None:
        return None
    attachment, slot = parts
    return f"/spark/cameras/{attachment}/{slot}"


def tactile_topic_prefix_for_sensor_key(sensor_key: str) -> str | None:
    parts = tactile_path_parts_for_sensor_key(sensor_key)
    if parts is None:
        return None
    arm, finger = parts
    return f"/spark/tactile/{arm}/{finger}"


def sensor_key_for_topic(topic: str) -> str | None:
    camera_match = _CAMERA_TOPIC_PATTERN.fullmatch(str(topic).strip())
    if camera_match:
        attachment = camera_match.group("attachment")
        slot = camera_match.group("slot")
        return f"/spark/cameras/{attachment}/{slot}"

    tactile_match = _TACTILE_TOPIC_PATTERN.fullmatch(str(topic).strip())
    if tactile_match:
        return f"/spark/tactile/{tactile_match.group('arm')}/{tactile_match.group('finger')}"

    return None


def sensor_topic_for_stream(sensor_key: str, stream: str) -> str | None:
    sensor_key = canonical_sensor_key(sensor_key)
    stream_name = str(stream).strip().lower()
    camera_prefix = camera_topic_prefix_for_sensor_key(sensor_key)
    if camera_prefix is not None:
        suffix = {
            "color": "color/image_raw",
            "depth": "depth/image_rect_raw",
            "color_metadata": "color/metadata",
            "depth_metadata": "depth/metadata",
        }.get(stream_name)
        return f"{camera_prefix}/{suffix}" if suffix else None

    tactile_prefix = tactile_topic_prefix_for_sensor_key(sensor_key)
    if tactile_prefix is not None:
        suffix = {
            "color": "color/image_raw",
        }.get(stream_name)
        return f"{tactile_prefix}/{suffix}" if suffix else None

    return None


def _arm_topic(arm: str, suffix: str) -> str:
    return f"/spark/{arm}/{suffix}"


def _sensor_field_suffix(sensor_key: str) -> str:
    camera_parts = camera_path_parts_for_sensor_key(sensor_key)
    if camera_parts is not None:
        attachment, slot = camera_parts
        return f"{attachment}.{slot}"
    tactile_parts = tactile_path_parts_for_sensor_key(sensor_key)
    if tactile_parts is not None:
        arm, finger = tactile_parts
        return f"tactile.{arm}.{finger}"
    raise ValueError(f"Unsupported sensor key: {sensor_key}")


def image_field_for_sensor_key(sensor_key: str) -> str:
    return f"observation.images.{_sensor_field_suffix(sensor_key)}"


def depth_field_for_sensor_key(sensor_key: str) -> str:
    return f"observation.depth.{_sensor_field_suffix(sensor_key)}"


def effective_profile_for_session(
    profile: dict[str, Any],
    active_arms: list[str] | tuple[str, ...] | set[str],
    sensor_keys: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any]:
    normalized_arms = normalize_active_arms(active_arms)
    normalized_sensor_keys = [
        canonical_sensor_key(sensor_key)
        for sensor_key in sensor_keys
        if canonical_sensor_key(sensor_key)
    ]

    effective = copy.deepcopy(profile)
    notes = effective.setdefault("notes", {})
    notes["arm_order"] = list(normalized_arms)
    notes["required_arms"] = list(normalized_arms)

    published = effective.setdefault("published", {})
    observation_state = published.setdefault("observation_state", {})
    action = published.setdefault("action", {})

    state_names: list[str] = []
    state_sources: dict[str, dict[str, str]] = {}
    for arm in normalized_arms:
        state_sources[arm] = {
            "joint_state": _arm_topic(arm, "robot/joint_state"),
            "eef_pose": _arm_topic(arm, "robot/eef_pose"),
            "gripper_state": _arm_topic(arm, "robot/gripper_state"),
            "tcp_wrench": _arm_topic(arm, "robot/tcp_wrench"),
        }
        for source_key, _count in _STATE_SOURCE_COUNTS:
            state_names.extend(f"{arm}_{name}" for name in _STATE_FIELD_TEMPLATES[source_key])
    observation_state["names"] = state_names
    observation_state["sources"] = state_sources

    action_names: list[str] = []
    action_sources: dict[str, dict[str, str]] = {}
    for arm in normalized_arms:
        action_sources[arm] = {
            "cmd_joint_state": _arm_topic(arm, "teleop/cmd_joint_state"),
            "cmd_gripper_state": _arm_topic(arm, "teleop/cmd_gripper_state"),
        }
        for source_key, _count in _ACTION_SOURCE_COUNTS:
            action_names.extend(f"{arm}_{name}" for name in _ACTION_FIELD_TEMPLATES[source_key])
    action["names"] = action_names
    action["sources"] = action_sources

    image_defaults = published.get("images", {})
    if not isinstance(image_defaults, dict):
        image_defaults = {}
    color_specs: list[dict[str, Any]] = []
    depth_defaults = effective.get("published_depth", {})
    if not isinstance(depth_defaults, dict):
        depth_defaults = {}
    depth_specs: list[dict[str, Any]] = []

    for sensor_key in sorted(dict.fromkeys(normalized_sensor_keys)):
        color_topic = sensor_topic_for_stream(sensor_key, "color")
        if color_topic:
            color_specs.append(
                {
                    "field": image_field_for_sensor_key(sensor_key),
                    "topic": color_topic,
                    "align": str(image_defaults.get("align", "nearest")),
                    "max_skew_ms": float(image_defaults.get("max_skew_ms", 25)),
                    "required": bool(image_defaults.get("required", False)),
                    "sensor_key": sensor_key,
                }
            )

        depth_topic = sensor_topic_for_stream(sensor_key, "depth")
        if depth_topic:
            depth_specs.append(
                {
                    "field": depth_field_for_sensor_key(sensor_key),
                    "topic": depth_topic,
                    "align": str(depth_defaults.get("align", "nearest")),
                    "max_skew_ms": float(depth_defaults.get("max_skew_ms", 25)),
                    "required": bool(depth_defaults.get("required", False)),
                    "unit": str(depth_defaults.get("unit", "raw_uint16")),
                    "sensor_key": sensor_key,
                }
            )

    published["images"] = color_specs
    effective["published_depth"] = depth_specs

    effective["raw_only_topics"] = []
    return effective

def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


def profile_path_for_name(profile_name: str) -> Path:
    if profile_name in PROFILE_NAME_TO_PATH:
        return PROFILE_NAME_TO_PATH[profile_name]
    return CONFIGS_DIR / f"{profile_name}.yaml"


def load_profile(path: str | Path = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    path_str = str(path)
    candidate = Path(path_str)
    if candidate.exists():
        return load_yaml(candidate)
    return load_yaml(profile_path_for_name(path_str))


def read_bag_metadata(bag_dir: str | Path) -> dict[str, Any]:
    metadata_path = Path(bag_dir) / "metadata.yaml"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Missing rosbag metadata: {metadata_path}")
    return load_yaml(metadata_path)


def detect_bag_storage_id(bag_dir: str | Path) -> str:
    bag_path = Path(bag_dir)
    metadata_path = bag_path / "metadata.yaml"
    if metadata_path.is_file():
        metadata = read_bag_metadata(bag_path)
        bag_info = metadata.get("rosbag2_bagfile_information", {})
        storage_id = bag_info.get("storage_identifier")
        if storage_id:
            return str(storage_id)

    if list(bag_path.glob("*.mcap")):
        return "mcap"
    if list(bag_path.glob("*.db3")):
        return "sqlite3"
    raise RuntimeError(f"Unable to detect rosbag storage backend under {bag_path}")


def normalize_active_arms(active_arms: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    normalized = {
        str(arm).strip().lower()
        for arm in active_arms
        if str(arm).strip()
    }
    invalid = sorted(normalized.difference(ARM_ORDER))
    if invalid:
        raise ValueError(f"Unsupported arm names: {invalid}")
    return [arm for arm in ARM_ORDER if arm in normalized]


def profile_required_arms(profile: dict[str, Any]) -> list[str]:
    notes_required = profile.get("notes", {}).get("required_arms")
    if isinstance(notes_required, list) and notes_required:
        return normalize_active_arms(notes_required)

    arm_sources = set(profile.get("published", {}).get("observation_state", {}).get("sources", {}))
    arm_sources.update(profile.get("published", {}).get("action", {}).get("sources", {}))
    return normalize_active_arms(arm_sources)


def resolve_profile_for_active_arms(
    profile_ref: str | Path | None,
    active_arms: list[str] | tuple[str, ...] | set[str],
) -> tuple[dict[str, Any], Path]:
    normalized_arms = normalize_active_arms(active_arms)
    if not normalized_arms:
        raise RuntimeError("No active arms detected. Cannot resolve a published profile.")

    if profile_ref in {None, "", "auto"}:
        resolved_path = DEFAULT_PROFILE_PATH
        return load_profile(resolved_path), resolved_path

    requested_profile = load_profile(profile_ref)
    requested_candidate_path = Path(str(profile_ref))
    requested_path = (
        requested_candidate_path
        if requested_candidate_path.exists()
        else profile_path_for_name(str(profile_ref))
    )
    requested_arms = profile_required_arms(requested_profile)
    if requested_arms == normalized_arms:
        return requested_profile, requested_path

    if not requested_arms:
        return requested_profile, requested_path

    raise RuntimeError(
        f"Requested profile {requested_profile.get('profile_name')} expects arms {requested_arms}, "
        f"but active arms are {normalized_arms}"
    )


def collect_candidate_topics(profile: dict[str, Any]) -> list[str]:
    topics: set[str] = set()

    published = profile.get("published", {})

    for arm_sources in published.get("observation_state", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    for arm_sources in published.get("action", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    for image_spec in published.get("images", []):
        topic = image_spec.get("topic")
        if topic:
            topics.add(topic)

    for depth_spec in profile.get("published_depth", []):
        topic = depth_spec.get("topic")
        if topic:
            topics.add(topic)

    teleop_activity_topic = str(profile.get("teleop_activity", {}).get("topic", "")).strip()
    if teleop_activity_topic:
        topics.add(teleop_activity_topic)

    topics.update(profile.get("raw_only_topics", []))
    return sorted(topics)


def required_topics_from_profile(profile: dict[str, Any]) -> list[str]:
    required = set()
    published = profile.get("published", {})

    for arm_sources in published.get("observation_state", {}).get("sources", {}).values():
        required.update(arm_sources.values())

    for arm_sources in published.get("action", {}).get("sources", {}).values():
        required.update(arm_sources.values())

    for image_spec in published.get("images", []):
        if image_spec.get("required", False):
            required.add(image_spec["topic"])

    for depth_spec in profile.get("published_depth", []):
        if depth_spec.get("required", False):
            required.add(depth_spec["topic"])

    teleop_activity = profile.get("teleop_activity", {})
    teleop_activity_topic = str(teleop_activity.get("topic", "")).strip()
    if teleop_activity_topic:
        required.add(teleop_activity_topic)

    return sorted(required)


def profile_compatibility_entry(
    *,
    profile: dict[str, Any],
    profile_path: str | Path,
    active_arms: list[str] | tuple[str, ...] | set[str],
    selected_topics: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any]:
    normalized_arms = normalize_active_arms(active_arms)
    required_arms = profile_required_arms(profile)
    selected_topic_set = {str(topic).strip() for topic in selected_topics if str(topic).strip()}
    missing_topics = [
        topic
        for topic in required_topics_from_profile(profile)
        if topic not in selected_topic_set
    ]

    reasons: list[str] = []
    if required_arms != normalized_arms:
        reasons.append(
            f"requires active arms {required_arms}, but session active arms are {normalized_arms}"
        )
    if missing_topics:
        reasons.append(f"missing required topics: {missing_topics}")

    return {
        "name": str(profile.get("profile_name", Path(profile_path).stem)),
        "path": str(profile_path),
        "compatible": not reasons,
        "required_arms": required_arms,
        "missing_topics": missing_topics,
        "reasons": reasons,
    }


def run_command(
    cmd: list[str],
    cwd: str | Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def get_git_commit(repo_root: str | Path = REPO_ROOT) -> str:
    return run_command(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()


def list_live_topics() -> dict[str, str]:
    result = run_command(["ros2", "topic", "list", "-t"])
    topics: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = _TOPIC_TYPE_PATTERN.match(line.strip())
        if not match:
            continue
        topics[match.group("topic")] = match.group("type")
    return topics


def read_param_dump(node_name: str) -> dict[str, Any]:
    result = run_command(["ros2", "param", "dump", node_name], timeout=3.0)
    data = yaml.safe_load(result.stdout) or {}
    node_params = data.get(node_name, {})
    ros_params = node_params.get("ros__parameters", {})
    if not isinstance(ros_params, dict):
        return {}
    return ros_params


def load_optional_sensor_overrides(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}

    data = load_yaml(path)
    sensors = data.get("sensors", data)

    if isinstance(sensors, list):
        out: dict[str, dict[str, Any]] = {}
        for entry in sensors:
            if not isinstance(entry, dict):
                continue
            sensor_key = canonical_sensor_key(str(entry.get("sensor_key", "")).strip())
            if not sensor_key:
                raise ValueError("Sensor list entries must define sensor_key.")
            entry_copy = dict(entry)
            entry_copy["sensor_key"] = sensor_key
            out[sensor_key] = entry_copy
        return out

    if isinstance(sensors, dict):
        out: dict[str, dict[str, Any]] = {}
        for sensor_key, value in sensors.items():
            if not isinstance(value, dict):
                continue
            canonical_key = canonical_sensor_key(str(sensor_key).strip())
            if not canonical_key:
                raise ValueError("Sensor mapping keys must be non-empty sensor keys.")
            out[canonical_key] = {**value, "sensor_key": canonical_key}
        return out

    raise ValueError("Sensor override file must contain a 'sensors' mapping or list.")


def _repo_relative_path(path: str | Path | None) -> str | None:
    if path in {None, ""}:
        return None
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def resolve_optional_calibration_results_path(path: str | Path | None) -> Path | None:
    if path in {None, ""}:
        candidate = DEFAULT_CALIBRATION_RESULTS_PATH
        return candidate if candidate.exists() else None

    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"Calibration results file not found: {candidate}")
    return candidate.resolve()


def load_optional_calibration_results(path: str | Path | None) -> tuple[dict[str, Any], Path | None]:
    resolved_path = resolve_optional_calibration_results_path(path)
    if resolved_path is None:
        return {}, None

    with resolved_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a JSON object in calibration results file {resolved_path}, "
            f"got {type(data).__name__}"
        )
    return data, resolved_path


def _calibration_snapshot_for_sensor_key(
    sensor_key: str,
    calibration_results: dict[str, Any],
    calibration_results_path: Path | None,
) -> dict[str, Any] | None:
    cameras = calibration_results.get("cameras", {})
    if not isinstance(cameras, dict):
        return None
    entry = cameras.get(sensor_key)
    if not isinstance(entry, dict):
        return None

    snapshot: dict[str, Any] = {
        "sensor_key": sensor_key,
        "source_file": _repo_relative_path(calibration_results_path),
    }
    for key in ("version", "timestamp", "tcp_frame_assumption", "charuco_config"):
        if key in calibration_results:
            snapshot[key] = calibration_results[key]
    for key in (
        "type",
        "serial_number",
        "intrinsics",
        "hand_eye_calibration",
        "extrinsics",
    ):
        if key in entry:
            snapshot[key] = entry[key]
    return snapshot


def infer_sensor_metadata(
    selected_topics: list[str],
    sensor_overrides: dict[str, dict[str, Any]] | None = None,
    calibration_results: dict[str, Any] | None = None,
    calibration_results_path: Path | None = None,
) -> list[dict[str, Any]]:
    sensor_overrides = sensor_overrides or {}
    calibration_results = calibration_results or {}
    sensors: list[dict[str, Any]] = []

    camera_sensor_keys = {
        sensor_key
        for sensor_key in (sensor_key_for_topic(topic) for topic in selected_topics)
        if sensor_key and camera_topic_prefix_for_sensor_key(sensor_key) is not None
    }
    for sensor_key in sorted(camera_sensor_keys):
        topic_prefix = camera_topic_prefix_for_sensor_key(sensor_key)
        if topic_prefix is None:
            continue
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_key": sensor_key,
            "modality": "rgbd_camera",
            "topic_names": sensor_topics,
            "serial_number": None,
        }

        try:
            params = read_param_dump(topic_prefix)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            params = {}

        serial = str(params.get("serial_no", "")).strip()
        if serial and serial not in {"''", '""'}:
            sensor["serial_number"] = serial.lstrip("_")
        device_type = str(params.get("device_type", "")).strip()
        if device_type and device_type not in {"''", '""'}:
            sensor["device_type"] = device_type
        firmware_version = str(params.get("firmware_version", "")).strip()
        if firmware_version and firmware_version not in {"''", '""'}:
            sensor["firmware_version"] = firmware_version
        color_profile = str(params.get("color_profile", "")).strip()
        depth_profile = str(params.get("depth_profile", "")).strip()
        stream_profiles: dict[str, Any] = {}
        if color_profile and color_profile not in {"''", '""'}:
            stream_profiles["color"] = color_profile
        if depth_profile and depth_profile not in {"''", '""'}:
            stream_profiles["depth"] = depth_profile
        if stream_profiles:
            sensor["stream_profiles"] = stream_profiles
        stream_intrinsics: dict[str, Any] = {}
        color_intrinsics_json = str(params.get("color_intrinsics_json", "")).strip()
        if color_intrinsics_json and color_intrinsics_json not in {"''", '""'}:
            try:
                stream_intrinsics["color"] = json.loads(color_intrinsics_json)
            except json.JSONDecodeError:
                pass
        depth_intrinsics_json = str(params.get("depth_intrinsics_json", "")).strip()
        if depth_intrinsics_json and depth_intrinsics_json not in {"''", '""'}:
            try:
                stream_intrinsics["depth"] = json.loads(depth_intrinsics_json)
            except json.JSONDecodeError:
                pass
        if stream_intrinsics:
            sensor["stream_intrinsics"] = stream_intrinsics
        depth_scale = params.get("depth_scale_meters_per_unit")
        if isinstance(depth_scale, (int, float)) and float(depth_scale) > 0.0:
            sensor["depth_scale_meters_per_unit"] = float(depth_scale)
        sensor.update(sensor_overrides.get(sensor_key, {}))
        sensor["sensor_key"] = sensor_key
        sensor.pop("model", None)
        sensor.pop("calibration_ref", None)
        sensor.pop("enabled_by_default", None)
        sensor.pop("display_label", None)
        calibration_snapshot = _calibration_snapshot_for_sensor_key(sensor_key, calibration_results, calibration_results_path)
        if calibration_snapshot is not None:
            sensor["calibration_snapshot"] = calibration_snapshot
        sensors.append(sensor)

    tactile_sensor_keys = {
        sensor_key
        for sensor_key in (sensor_key_for_topic(topic) for topic in selected_topics)
        if sensor_key and tactile_topic_prefix_for_sensor_key(sensor_key) is not None
    }
    for sensor_key in sorted(tactile_sensor_keys):
        topic_prefix = tactile_topic_prefix_for_sensor_key(sensor_key)
        if topic_prefix is None:
            continue
        arm, mount_site = tactile_path_parts_for_sensor_key(sensor_key) or ("lightning", "finger_left")
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_key": sensor_key,
            "modality": "tactile_rgb",
            "topic_names": sensor_topics,
            "serial_number": None,
        }

        node_name = f"/gelsight_{arm}_{mount_site}_bridge"
        try:
            params = read_param_dump(node_name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            params = {}

        device_path = str(params.get("device_path", "")).strip()
        if device_path and device_path not in {"''", '""'}:
            sensor["device_path"] = device_path

        device_index = params.get("device_index")
        if isinstance(device_index, (int, float)) and int(device_index) >= 0:
            sensor["device_index"] = int(device_index)

        frame_id = str(params.get("frame_id", "")).strip()
        if frame_id and frame_id not in {"''", '""'}:
            sensor["frame_id"] = frame_id

        encoding = str(params.get("encoding", "")).strip()
        if encoding and encoding not in {"''", '""'}:
            sensor["encoding"] = encoding

        fps = params.get("fps")
        if isinstance(fps, (int, float)):
            sensor["fps"] = float(fps)

        capture_width = params.get("capture_width")
        if isinstance(capture_width, (int, float)) and int(capture_width) > 0:
            sensor["capture_width"] = int(capture_width)

        capture_height = params.get("capture_height")
        if isinstance(capture_height, (int, float)) and int(capture_height) > 0:
            sensor["capture_height"] = int(capture_height)

        output_width = params.get("output_width")
        if isinstance(output_width, (int, float)) and int(output_width) > 0:
            sensor["output_width"] = int(output_width)

        output_height = params.get("output_height")
        if isinstance(output_height, (int, float)) and int(output_height) > 0:
            sensor["output_height"] = int(output_height)

        border_fraction = params.get("border_fraction")
        crop_applied = params.get("crop_applied")
        preprocessing_pipeline = str(params.get("preprocessing_pipeline", "")).strip()
        preprocessing: dict[str, Any] = {}
        if preprocessing_pipeline and preprocessing_pipeline not in {"''", '""'}:
            preprocessing["pipeline"] = preprocessing_pipeline
        if isinstance(border_fraction, (int, float)):
            preprocessing["border_fraction"] = float(border_fraction)
        if isinstance(crop_applied, bool):
            preprocessing["crop_applied"] = crop_applied
        if preprocessing:
            sensor["preprocessing"] = preprocessing

        sensor.update(sensor_overrides.get(sensor_key, {}))
        sensor["sensor_key"] = sensor_key
        sensor.pop("model", None)
        sensor.pop("calibration_ref", None)
        sensor.pop("enabled_by_default", None)
        sensor.pop("display_label", None)
        sensors.append(sensor)

    return sensors


def build_recorded_topics_snapshot(
    *,
    selected_topics: list[str],
    live_topics: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "topic": topic,
            "message_type": live_topics[topic],
        }
        for topic in selected_topics
    ]


def manifest_episode(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["episode"]


def manifest_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["profile"]


def manifest_sensors(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sensors = manifest["sensors"]
    if not isinstance(sensors, dict):
        raise TypeError("Manifest sensors section must be an object with a devices list.")
    devices = sensors.get("devices", [])
    if not isinstance(devices, list):
        raise TypeError("Manifest sensors.devices must be a list.")
    return list(devices)


def manifest_episode_id(manifest: dict[str, Any]) -> str:
    return str(manifest_episode(manifest)["episode_id"])


def manifest_task_name(manifest: dict[str, Any]) -> str:
    return str(manifest_episode(manifest)["task_name"])


def manifest_language_instruction(manifest: dict[str, Any]) -> str | None:
    value = manifest_episode(manifest).get("language_instruction")
    return str(value) if value else None


def manifest_active_arms(manifest: dict[str, Any]) -> list[str]:
    return list(manifest_episode(manifest).get("active_arms", []))

def manifest_profile_name(manifest: dict[str, Any]) -> str:
    return str(manifest_profile(manifest)["name"])


def manifest_clock_policy(manifest: dict[str, Any]) -> str:
    return str(manifest_profile(manifest)["clock_policy"])


def manifest_topic_types(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(entry["topic"]): str(entry["message_type"])
        for entry in manifest.get("recorded_topics", [])
    }


def parse_task_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def make_episode_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("episode-%Y%m%d-%H%M%S")


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def build_notes_template(manifest: dict[str, Any]) -> str:
    episode = manifest_episode(manifest)
    profile = manifest_profile(manifest)
    lines = [f"# {episode['episode_id']}", ""]
    lines.extend(
        [
            f"- task_name: {episode['task_name']}",
            f"- language_instruction: {episode.get('language_instruction') or ''}",
        ]
    )
    lines.extend(
        [
            f"- active_arms: {', '.join(episode.get('active_arms', [])) or 'unknown'}",
            f"- operator: {episode['operator']}",
            f"- profile_name: {profile['name']}",
            f"- clock_policy: {profile['clock_policy']}",
            "",
            "## Notes",
            "",
            "- Fill in task-specific notes here.",
            "- Record any runtime anomalies, dropped sensors, or calibration issues.",
        ]
    )
    return "\n".join(lines) + "\n"


def now_ns() -> int:
    return time.time_ns()
