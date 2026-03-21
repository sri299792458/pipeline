#!/usr/bin/python3

"""Shared helpers for the V1 data pipeline scripts."""

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
DEFAULT_BAG_STORAGE_ID = "mcap"
DEFAULT_BAG_STORAGE_PRESET_PROFILE = "zstd_fast"
ARM_ORDER = ("lightning", "thunder")
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

    return sorted(required)


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


def infer_sensor_metadata(
    selected_topics: list[str],
    sensor_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sensor_overrides = sensor_overrides or {}
    sensors: list[dict[str, Any]] = []

    camera_specs = [
        {
            "sensor_name": "wrist",
            "topic_prefix": "/spark/cameras/wrist",
            "sensor_id": "cam_wrist_0",
            "modality": "rgbd_camera",
            "attached_to": "unknown",
            "mount_site": "wrist",
            "model": None,
        },
        {
            "sensor_name": "scene",
            "topic_prefix": "/spark/cameras/scene",
            "sensor_id": "cam_scene_0",
            "modality": "rgbd_camera",
            "attached_to": "world",
            "mount_site": "scene_0",
            "model": None,
        },
    ]
    for spec in camera_specs:
        sensor_name = spec["sensor_name"]
        topic_prefix = spec["topic_prefix"]
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_id": spec["sensor_id"],
            "modality": spec["modality"],
            "attached_to": spec["attached_to"],
            "mount_site": spec["mount_site"],
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": spec["model"],
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

        sensor.update(sensor_overrides.get(sensor_name, {}))
        sensors.append(sensor)

    tactile_specs = [
        {
            "sensor_name": "left",
            "topic_prefix": "/spark/tactile/left",
            "node_name": "gelsight_left_bridge",
            "sensor_id": "tac_finger_left_0",
            "modality": "tactile_rgb",
            "attached_to": "unknown",
            "mount_site": "finger_left",
            "model": "GelSight Mini",
        },
        {
            "sensor_name": "right",
            "topic_prefix": "/spark/tactile/right",
            "node_name": "gelsight_right_bridge",
            "sensor_id": "tac_finger_right_0",
            "modality": "tactile_rgb",
            "attached_to": "unknown",
            "mount_site": "finger_right",
            "model": "GelSight Mini",
        },
    ]
    for spec in tactile_specs:
        sensor_name = spec["sensor_name"]
        topic_prefix = spec["topic_prefix"]
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_id": spec["sensor_id"],
            "modality": spec["modality"],
            "attached_to": spec["attached_to"],
            "mount_site": spec["mount_site"],
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": spec["model"],
            "calibration_ref": None,
        }
        try:
            params = read_param_dump(spec["node_name"])
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

        sensor.update(sensor_overrides.get(sensor_name, {}))
        sensors.append(sensor)

    return sensors


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
    lines = [
        f"# {manifest['episode_id']}",
        "",
        f"- dataset_id: {manifest['dataset_id']}",
        f"- task_name: {manifest['task_name']}",
        f"- language_instruction: {manifest.get('language_instruction') or ''}",
        f"- robot_id: {manifest['robot_id']}",
        f"- active_arms: {', '.join(manifest.get('active_arms', [])) or 'unknown'}",
        f"- operator: {manifest['operator']}",
        f"- mapping_profile: {manifest['mapping_profile']}",
        f"- clock_policy: {manifest['clock_policy']}",
        "",
        "## Notes",
        "",
        "- Fill in task-specific notes here.",
        "- Record any runtime anomalies, dropped sensors, or calibration issues.",
    ]
    return "\n".join(lines) + "\n"


def now_ns() -> int:
    return time.time_ns()
