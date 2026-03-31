#!/usr/bin/python3

"""Shared helpers for the V2 data pipeline scripts."""

from __future__ import annotations

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
CAMERA_ROLE_CHOICES = (
    "lightning_wrist_1",
    "thunder_wrist_1",
    "scene_1",
    "scene_2",
    "scene_3",
)
TACTILE_ROLE_CHOICES = (
    "lightning_finger_left",
    "lightning_finger_right",
    "thunder_finger_left",
    "thunder_finger_right",
)
MANIFEST_SCHEMA_VERSION = 8
PROFILE_NAME_TO_PATH = {
    "multisensor_20hz": CONFIGS_DIR / "multisensor_20hz.yaml",
    "multisensor_20hz_lightning": CONFIGS_DIR / "multisensor_20hz_lightning.yaml",
    "multisensor_20hz_thunder": CONFIGS_DIR / "multisensor_20hz_thunder.yaml",
}
ACTIVE_ARMS_TO_PROFILE_NAME = {
    ("lightning", "thunder"): "multisensor_20hz",
    ("lightning",): "multisensor_20hz_lightning",
    ("thunder",): "multisensor_20hz_thunder",
}

_TOPIC_TYPE_PATTERN = re.compile(r"^(?P<topic>/\S+)\s+\[(?P<type>[^\]]+)\]\s*$")
_CAMERA_ROLE_PATTERN = re.compile(r"^(?P<arm>lightning|thunder)_(?P<slot>wrist_\d+)$")
_SCENE_ROLE_PATTERN = re.compile(r"^(?P<slot>scene_\d+)$")
_TACTILE_ROLE_PATTERN = re.compile(r"^(?P<arm>lightning|thunder)_(?P<finger>finger_left|finger_right)$")
_CAMERA_TOPIC_PATTERN = re.compile(
    r"^/spark/cameras/(?P<attachment>lightning|thunder|world)/(?P<slot>[a-z0-9_]+)/"
    r"(?P<suffix>color/image_raw|depth/image_rect_raw|color/metadata|depth/metadata)$"
)
_TACTILE_TOPIC_PATTERN = re.compile(
    r"^/spark/tactile/(?P<arm>lightning|thunder)/(?P<finger>finger_left|finger_right)/"
    r"(?P<suffix>color/image_raw|depth/image_raw|marker_offset)$"
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


def camera_path_parts_for_role(role: str) -> tuple[str, str] | None:
    role_str = str(role).strip()
    if not role_str:
        return None
    scene_match = _SCENE_ROLE_PATTERN.fullmatch(role_str)
    if scene_match:
        return "world", scene_match.group("slot")
    wrist_match = _CAMERA_ROLE_PATTERN.fullmatch(role_str)
    if wrist_match:
        return wrist_match.group("arm"), wrist_match.group("slot")
    return None


def tactile_path_parts_for_role(role: str) -> tuple[str, str] | None:
    match = _TACTILE_ROLE_PATTERN.fullmatch(str(role).strip())
    if not match:
        return None
    return match.group("arm"), match.group("finger")


def camera_topic_prefix_for_role(role: str) -> str | None:
    parts = camera_path_parts_for_role(role)
    if parts is None:
        return None
    attachment, slot = parts
    return f"/spark/cameras/{attachment}/{slot}"


def tactile_topic_prefix_for_role(role: str) -> str | None:
    parts = tactile_path_parts_for_role(role)
    if parts is None:
        return None
    arm, finger = parts
    return f"/spark/tactile/{arm}/{finger}"


def role_choices_for_kind(kind: str) -> list[str]:
    if kind == "realsense":
        return list(CAMERA_ROLE_CHOICES)
    if kind == "gelsight":
        return list(TACTILE_ROLE_CHOICES)
    return []


def sensor_role_for_topic(topic: str) -> str | None:
    camera_match = _CAMERA_TOPIC_PATTERN.fullmatch(str(topic).strip())
    if camera_match:
        attachment = camera_match.group("attachment")
        slot = camera_match.group("slot")
        if attachment == "world":
            return slot
        return f"{attachment}_{slot}"

    tactile_match = _TACTILE_TOPIC_PATTERN.fullmatch(str(topic).strip())
    if tactile_match:
        return f"{tactile_match.group('arm')}_{tactile_match.group('finger')}"

    return None


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

    resolved_profile_name = ACTIVE_ARMS_TO_PROFILE_NAME.get(tuple(normalized_arms))
    if resolved_profile_name is None:
        raise RuntimeError(f"Unsupported active-arm combination: {normalized_arms}")

    if profile_ref in {None, "", "auto"}:
        resolved_path = profile_path_for_name(resolved_profile_name)
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

    if requested_profile.get("profile_name") == DEFAULT_PROFILE_PATH.stem:
        resolved_path = profile_path_for_name(resolved_profile_name)
        return load_profile(resolved_path), resolved_path

    raise RuntimeError(
        f"Requested profile {requested_profile.get('profile_name')} expects arms {requested_arms}, "
        f"but active arms are {normalized_arms}"
    )


def list_known_profiles() -> list[tuple[dict[str, Any], Path]]:
    profiles: list[tuple[dict[str, Any], Path]] = []
    for profile_name in sorted(PROFILE_NAME_TO_PATH):
        profile_path = profile_path_for_name(profile_name)
        profiles.append((load_profile(profile_path), profile_path))
    return profiles


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

    teleop_activity = profile.get("teleop_activity", {})
    teleop_activity_topic = str(teleop_activity.get("topic", "")).strip()
    if teleop_activity_topic and bool(teleop_activity.get("required_for_record", False)):
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
            sensor_name = entry.get("sensor_name")
            if sensor_name:
                out[sensor_name] = entry
        return out

    if isinstance(sensors, dict):
        return {
            sensor_name: value
            for sensor_name, value in sensors.items()
            if isinstance(value, dict)
        }

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


def _calibration_snapshot_for_role(
    role: str,
    calibration_results: dict[str, Any],
    calibration_results_path: Path | None,
) -> dict[str, Any] | None:
    cameras = calibration_results.get("cameras", {})
    if not isinstance(cameras, dict):
        return None
    entry = cameras.get(role)
    if not isinstance(entry, dict):
        return None

    snapshot: dict[str, Any] = {
        "role": role,
        "source_file": _repo_relative_path(calibration_results_path),
    }
    for key in ("version", "timestamp", "tcp_frame_assumption", "charuco_config"):
        if key in calibration_results:
            snapshot[key] = calibration_results[key]
    for key in (
        "type",
        "serial_number",
        "model",
        "attached_to",
        "mount_site",
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

    camera_roles = {
        role
        for role in (sensor_role_for_topic(topic) for topic in selected_topics)
        if role and camera_topic_prefix_for_role(role) is not None
    }
    for role in sorted(camera_roles):
        topic_prefix = camera_topic_prefix_for_role(role)
        if topic_prefix is None:
            continue
        attachment, mount_site = camera_path_parts_for_role(role) or ("world", role)
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "role": role,
            "sensor_id": f"cam_{role}",
            "modality": "rgbd_camera",
            "attached_to": attachment,
            "mount_site": mount_site,
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": None,
            "calibration_ref": None,
        }

        try:
            params = read_param_dump(topic_prefix)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            params = {}

        serial = str(params.get("serial_no", "")).strip()
        if serial and serial not in {"''", '""'}:
            sensor["serial_number"] = serial.lstrip("_")
        if "device_type" in params and params["device_type"] not in {"", "''", '""'}:
            sensor["model"] = params["device_type"]

        sensor.update(sensor_overrides.get(role, {}))
        calibration_snapshot = _calibration_snapshot_for_role(role, calibration_results, calibration_results_path)
        if calibration_snapshot is not None:
            sensor["calibration_snapshot"] = calibration_snapshot
        sensors.append(sensor)

    tactile_roles = {
        role
        for role in (sensor_role_for_topic(topic) for topic in selected_topics)
        if role and tactile_topic_prefix_for_role(role) is not None
    }
    for role in sorted(tactile_roles):
        topic_prefix = tactile_topic_prefix_for_role(role)
        if topic_prefix is None:
            continue
        arm, mount_site = tactile_path_parts_for_role(role) or ("lightning", "finger_left")
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "role": role,
            "sensor_id": f"tac_{role}_0",
            "modality": "tactile_rgb",
            "attached_to": arm,
            "mount_site": mount_site,
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": "GelSight Mini",
            "calibration_ref": None,
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

        sensor.update(sensor_overrides.get(role, {}))
        sensors.append(sensor)

    return sensors


def _sensor_ids_by_topic(sensors: list[dict[str, Any]]) -> dict[str, str]:
    topic_to_sensor: dict[str, str] = {}
    for sensor in sensors:
        sensor_id = str(sensor.get("sensor_id", "")).strip()
        if not sensor_id:
            continue
        for topic in sensor.get("topic_names", []):
            topic_to_sensor[str(topic)] = sensor_id
    return topic_to_sensor


def _rate_range(min_hz: float | None, max_hz: float | None) -> dict[str, float | None]:
    return {
        "min_hz": float(min_hz) if min_hz is not None else None,
        "max_hz": float(max_hz) if max_hz is not None else None,
    }


def _static_topic_descriptor(topic: str) -> dict[str, Any]:
    if topic == "/spark/session/teleop_active":
        return {
            "producer": {
                "process": "TeleopSoftware/Spark/SparkNode.py",
                "node": "SparkNode",
                "upstream_source": "SPARK serial packet enable_switch from the shared foot pedal",
            },
            "semantics": {
                "kind": "teleop_activity",
                "value_meaning": "Boolean teleop activity mask",
                "units": "boolean",
                "convention": "true=pedal_active",
            },
            "timestamp": {
                "carrier": "bag_timestamp_ns",
                "meaning": "host receive/publish time of the SPARK packet carrying the enable state",
                "vocabulary": "host_capture_time_v1",
                "has_header": False,
            },
            "expected_rate_hz": _rate_range(20, 200),
        }

    camera_match = _CAMERA_TOPIC_PATTERN.fullmatch(topic)
    if camera_match:
        attachment = camera_match.group("attachment")
        slot = camera_match.group("slot")
        suffix = camera_match.group("suffix")
        kind = "raw_sensor"
        value_meaning = "RGB image observation" if suffix == "color/image_raw" else "Depth image"
        units = None if suffix == "color/image_raw" else "millimeters"
        return {
            "producer": {
                "process": "data_pipeline/realsense_bridge.py",
                "node": f"/spark/cameras/{attachment}/{slot}",
                "upstream_source": f"Intel RealSense {attachment}/{slot} stream",
            },
            "semantics": {
                "kind": kind,
                "value_meaning": value_meaning,
                "units": units,
                "convention": None,
            },
            "timestamp": {
                "carrier": "header.stamp",
                "meaning": "host ROS time assigned immediately after wait_for_frames() returns",
                "vocabulary": "host_capture_time_v1",
                "has_header": True,
            },
            "expected_rate_hz": _rate_range(20, 30),
        }

    tactile_match = _TACTILE_TOPIC_PATTERN.fullmatch(topic)
    if tactile_match:
        arm = tactile_match.group("arm")
        finger = tactile_match.group("finger")
        suffix = tactile_match.group("suffix")
        kind = "raw_sensor" if suffix == "color/image_raw" else "derived_sensor"
        value_meaning = {
            "color/image_raw": "GelSight tactile RGB frame",
            "depth/image_raw": "GelSight derived depth image",
            "marker_offset": "GelSight marker displacement cloud",
        }[suffix]
        units = "millimeters" if suffix == "depth/image_raw" else None
        return {
            "producer": {
                "process": "data_pipeline/gelsight_bridge.py",
                "node": f"/gelsight_{arm}_{finger}_bridge",
                "upstream_source": f"GelSight Mini {arm}/{finger} tactile stream",
            },
            "semantics": {
                "kind": kind,
                "value_meaning": value_meaning,
                "units": units,
                "convention": None,
            },
            "timestamp": {
                "carrier": "header.stamp",
                "meaning": "host ROS time assigned immediately after camera.read() returns",
                "vocabulary": "host_capture_time_v1",
                "has_header": True,
            },
            "expected_rate_hz": _rate_range(15, 30),
        }

    robot_match = re.fullmatch(
        r"/spark/(lightning|thunder)/(robot|teleop)/(joint_state|eef_pose|tcp_wrench|gripper_state|cmd_joint_state|cmd_gripper_state)",
        topic,
    )
    if robot_match:
        arm, namespace, signal = robot_match.groups()
        if namespace == "robot":
            timestamp = {
                "carrier": "header.stamp",
                "meaning": "host ROS time assigned once for the robot/control update tick",
                "vocabulary": "control_tick_time_v1",
                "has_header": True,
            }
            kind = "measured_state"
        else:
            timestamp = {
                "carrier": "header.stamp",
                "meaning": "host ROS time when the teleop/runtime command is issued",
                "vocabulary": "command_issue_time_v1",
                "has_header": True,
            }
            kind = "command"
        semantics = {
            "joint_state": ("Measured UR joint positions", "radians", None),
            "eef_pose": ("Measured UR end-effector pose", "meters_and_radians", None),
            "tcp_wrench": ("Measured UR TCP wrench", "newtons_and_newton_meters", None),
            "gripper_state": ("Measured gripper opening", "unitless_0_to_1", "0=open,1=closed"),
            "cmd_joint_state": ("Issued joint target", "radians", None),
            "cmd_gripper_state": ("Issued gripper opening target", "unitless_0_to_1", "0=open,1=closed"),
        }[signal]
        upstream_source = {
            "joint_state": "UR RTDE receive",
            "eef_pose": "UR RTDE TCP pose",
            "tcp_wrench": "UR RTDE force-torque",
            "gripper_state": "Robotiq gripper state",
            "cmd_joint_state": "Spark teleop command path",
            "cmd_gripper_state": "Spark-derived gripper command path",
        }[signal]
        return {
            "producer": {
                "process": "TeleopSoftware/launch.py",
                "node": "gui_node",
                "upstream_source": f"{arm} {upstream_source}",
            },
            "semantics": {
                "kind": kind,
                "value_meaning": semantics[0],
                "units": semantics[1],
                "convention": semantics[2],
            },
            "timestamp": timestamp,
            "expected_rate_hz": _rate_range(20, 200),
        }

    return {
        "producer": {
            "process": None,
            "node": None,
            "upstream_source": None,
        },
        "semantics": {
            "kind": "unknown",
            "value_meaning": None,
            "units": None,
            "convention": None,
        },
        "timestamp": {
            "carrier": "unknown",
            "meaning": "No static topic-contract entry available",
            "vocabulary": None,
            "has_header": None,
        },
        "expected_rate_hz": _rate_range(None, None),
    }


def _profile_topic_usage(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}

    def entry(topic: str) -> dict[str, Any]:
        return usage.setdefault(
            topic,
            {
                "roles": [],
                "published_fields": [],
                "required_for_convert": False,
                "published": False,
                "raw_only": False,
            },
        )

    observation_state = profile.get("published", {}).get("observation_state", {})
    state_names = list(observation_state.get("names", []))
    state_index = 0
    for arm, arm_sources in observation_state.get("sources", {}).items():
        for source_key, count in _STATE_SOURCE_COUNTS:
            topic = str(arm_sources.get(source_key, "")).strip()
            if not topic:
                continue
            topic_entry = entry(topic)
            topic_entry["roles"].append("published_observation_state_source")
            topic_entry["published_fields"].extend(state_names[state_index : state_index + count])
            topic_entry["required_for_convert"] = True
            topic_entry["published"] = True
            state_index += count

    action = profile.get("published", {}).get("action", {})
    action_names = list(action.get("names", []))
    action_index = 0
    for arm, arm_sources in action.get("sources", {}).items():
        for source_key, count in _ACTION_SOURCE_COUNTS:
            topic = str(arm_sources.get(source_key, "")).strip()
            if not topic:
                continue
            topic_entry = entry(topic)
            topic_entry["roles"].append("published_action_source")
            topic_entry["published_fields"].extend(action_names[action_index : action_index + count])
            topic_entry["required_for_convert"] = True
            topic_entry["published"] = True
            action_index += count

    for image_spec in profile.get("published", {}).get("images", []):
        topic = str(image_spec.get("topic", "")).strip()
        if not topic:
            continue
        topic_entry = entry(topic)
        topic_entry["roles"].append("published_image_source")
        field = str(image_spec.get("field", "")).strip()
        if field:
            topic_entry["published_fields"].append(field)
        if bool(image_spec.get("required", False)):
            topic_entry["required_for_convert"] = True
        topic_entry["published"] = True

    for depth_spec in profile.get("published_depth", []):
        topic = str(depth_spec.get("topic", "")).strip()
        if not topic:
            continue
        topic_entry = entry(topic)
        topic_entry["roles"].append("published_depth_source")
        field = str(depth_spec.get("field", "")).strip()
        if field:
            topic_entry["published_fields"].append(field)
        if bool(depth_spec.get("required", False)):
            topic_entry["required_for_convert"] = True
        topic_entry["published"] = True

    for topic in profile.get("raw_only_topics", []):
        topic_entry = entry(str(topic))
        topic_entry["roles"].append("raw_only")
        topic_entry["raw_only"] = True

    teleop_activity = profile.get("teleop_activity", {})
    teleop_activity_topic = str(teleop_activity.get("topic", "")).strip()
    if teleop_activity_topic:
        topic_entry = entry(teleop_activity_topic)
        topic_entry["roles"].append("teleop_activity")
        topic_entry["roles"].append("raw_only_conversion_aid")
        topic_entry["raw_only"] = True
        if bool(teleop_activity.get("required_for_convert", False)):
            topic_entry["required_for_convert"] = True

    for topic_entry in usage.values():
        topic_entry["roles"] = sorted(set(topic_entry["roles"]))
        topic_entry["published_fields"] = list(dict.fromkeys(topic_entry["published_fields"]))

    return usage


def build_recorded_topics_snapshot(
    *,
    profile: dict[str, Any],
    selected_topics: list[str],
    live_topics: dict[str, str],
    sensors: list[dict[str, Any]],
    extra_topics: list[str] | None = None,
) -> list[dict[str, Any]]:
    sensor_ids_by_topic = _sensor_ids_by_topic(sensors)
    usage = _profile_topic_usage(profile)
    required_for_record = set(required_topics_from_profile(profile))
    extra_topic_set = {str(topic) for topic in (extra_topics or [])}

    entries: list[dict[str, Any]] = []
    for topic in selected_topics:
        descriptor = _static_topic_descriptor(topic)
        topic_usage = usage.get(
            topic,
            {
                "roles": [],
                "published_fields": [],
                "required_for_convert": False,
                "published": False,
                "raw_only": True,
            },
        )
        roles = list(topic_usage["roles"])
        if topic in extra_topic_set:
            roles.append("extra_topic")
        entries.append(
            {
                "topic": topic,
                "message_type": live_topics[topic],
                "producer": descriptor["producer"],
                "semantics": descriptor["semantics"],
                "timestamp": descriptor["timestamp"],
                "expected_rate_hz": descriptor["expected_rate_hz"],
                "sensor_id": sensor_ids_by_topic.get(topic),
                "usage": {
                    "required_for_record": topic in required_for_record,
                    "required_for_convert": bool(topic_usage["required_for_convert"]),
                    "published": bool(topic_usage["published"]),
                    "raw_only": bool(topic_usage["raw_only"]),
                    "roles": sorted(set(roles)),
                    "published_fields": list(topic_usage["published_fields"]),
                },
            }
        )
    return entries


def manifest_episode(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["episode"]


def manifest_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["profile"]


def manifest_capture(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["capture"]


def manifest_sensors(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sensors = manifest.get("sensors", {})
    if isinstance(sensors, dict):
        return list(sensors.get("devices", []))
    return list(sensors)


def manifest_dataset_id(manifest: dict[str, Any]) -> str | None:
    value = manifest_episode(manifest).get("dataset_id")
    return str(value) if value not in {"", None} else None


def manifest_episode_id(manifest: dict[str, Any]) -> str:
    return str(manifest_episode(manifest)["episode_id"])


def manifest_task_name(manifest: dict[str, Any]) -> str:
    return str(manifest_episode(manifest)["task_name"])


def manifest_language_instruction(manifest: dict[str, Any]) -> str | None:
    value = manifest_episode(manifest).get("language_instruction")
    return str(value) if value else None


def manifest_active_arms(manifest: dict[str, Any]) -> list[str]:
    return list(manifest_episode(manifest).get("active_arms", []))


def manifest_robot_id(manifest: dict[str, Any]) -> str | None:
    value = manifest_episode(manifest).get("robot_id")
    return str(value) if value not in {"", None} else None


def manifest_profile_name(manifest: dict[str, Any]) -> str:
    return str(manifest_profile(manifest)["name"])


def manifest_profile_version(manifest: dict[str, Any]) -> int:
    return int(manifest_profile(manifest)["version"])


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
    dataset_id = episode.get("dataset_id")
    if dataset_id not in {"", None}:
        lines.append(f"- dataset_id: {dataset_id}")
    lines.extend(
        [
            f"- task_name: {episode['task_name']}",
            f"- language_instruction: {episode.get('language_instruction') or ''}",
        ]
    )
    robot_id = episode.get("robot_id")
    if robot_id not in {"", None}:
        lines.append(f"- robot_id: {robot_id}")
    lines.extend(
        [
            f"- active_arms: {', '.join(episode.get('active_arms', [])) or 'unknown'}",
            f"- operator: {episode['operator']}",
            f"- mapping_profile: {profile['name']}",
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
