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
DEFAULT_PROFILE_PATH = REPO_ROOT / "data_pipeline" / "configs" / "multisensor_20hz.yaml"
DEFAULT_RAW_EPISODES_DIR = REPO_ROOT / "raw_episodes"

_TOPIC_TYPE_PATTERN = re.compile(r"^(?P<topic>/\S+)\s+\[(?P<type>[^\]]+)\]\s*$")


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


def load_profile(path: str | Path = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    return load_yaml(path)


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


def run_command(cmd: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        text=True,
        capture_output=True,
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
    result = run_command(["ros2", "param", "dump", node_name])
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
        ("wrist", "/spark/cameras/wrist", "realsense"),
        ("scene", "/spark/cameras/scene", "realsense"),
    ]
    for sensor_name, topic_prefix, sensor_type in camera_specs:
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_name": sensor_name,
            "sensor_type": sensor_type,
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": None,
            "firmware_version": None,
            "resolution": None,
            "fps": None,
            "driver_node": topic_prefix,
            "calibration_ref": None,
        }

        try:
            params = read_param_dump(topic_prefix)
        except subprocess.CalledProcessError:
            params = {}

        serial = str(params.get("serial_no", "")).strip()
        if serial and serial not in {"''", '""'}:
            sensor["serial_number"] = serial.lstrip("_")
        if "device_type" in params and params["device_type"] not in {"", "''", '""'}:
            sensor["model"] = params["device_type"]
        if "firmware_version" in params and params["firmware_version"] not in {"", "''", '""'}:
            sensor["firmware_version"] = params["firmware_version"]

        color_profile = (
            params.get("color_profile")
            or params.get("rgb_camera.color_profile")
            or params.get("depth_module.color_profile")
        )
        if isinstance(color_profile, str):
            profile_tokens = color_profile.split(",")
            if len(profile_tokens) == 3:
                sensor["resolution"] = f"{profile_tokens[0]}x{profile_tokens[1]}"
                sensor["fps"] = profile_tokens[2]

        sensor.update(sensor_overrides.get(sensor_name, {}))
        sensors.append(sensor)

    tactile_specs = [
        ("left", "/spark/tactile/left", "gelsight"),
        ("right", "/spark/tactile/right", "gelsight"),
    ]
    for sensor_name, topic_prefix, sensor_type in tactile_specs:
        sensor_topics = [topic for topic in selected_topics if topic.startswith(topic_prefix + "/")]
        if not sensor_topics:
            continue

        sensor = {
            "sensor_name": sensor_name,
            "sensor_type": sensor_type,
            "topic_names": sensor_topics,
            "serial_number": None,
            "model": "GelSight Mini",
            "firmware_version": None,
            "resolution": None,
            "fps": None,
            "driver_node": f"/gelsight_{sensor_name}_bridge",
            "calibration_ref": None,
        }
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
        f"- robot_id: {manifest['robot_id']}",
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
