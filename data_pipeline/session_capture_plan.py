#!/usr/bin/env python3

"""Build the V2 session profile object used by the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_role,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    resolve_profile_for_active_arms,
    sensor_role_for_topic,
    tactile_path_parts_for_role,
)


def _canonical_role_from_sensor_name(sensor_name: str, sensor: dict[str, Any]) -> str:
    sensor_name = str(sensor_name).strip()
    if camera_path_parts_for_role(sensor_name) is not None or tactile_path_parts_for_role(sensor_name) is not None:
        return sensor_name

    attached_to = str(sensor.get("attached_to", "")).strip()
    mount_site = str(sensor.get("mount_site", "")).strip()

    if mount_site.startswith("scene_"):
        return mount_site
    if mount_site.startswith("wrist_") and attached_to:
        return f"{attached_to}_{mount_site}"
    if mount_site.startswith("finger_") and attached_to:
        return f"{attached_to}_{mount_site}"
    return sensor_name


def _sensor_for_role(
    role: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any]]:
    role_str = str(role).strip()
    if not role_str:
        return None, {}
    for sensor_name, sensor in sensor_overrides.items():
        if _canonical_role_from_sensor_name(sensor_name, sensor) == role_str:
            return sensor_name, sensor
    return None, {}


def _device_metadata(entry: dict[str, Any], sensor: dict[str, Any]) -> dict[str, Any]:
    merged = dict(sensor)
    for key in ("sensor_id", "attached_to", "mount_site", "model", "calibration_ref"):
        value = entry.get(key)
        if value not in {"", None}:
            merged[key] = value
    return merged


def _device_from_session_config(
    *,
    entry: dict[str, Any],
    sensor_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    kind = str(entry.get("kind", "")).strip() or "device"
    role = str(entry.get("role", "")).strip()
    identifier = str(entry.get("identifier", "")).strip()
    serial_number = str(entry.get("serial_number", "")).strip()
    device_path = str(entry.get("device_path", "")).strip()

    _sensor_name, sensor = _sensor_for_role(role, sensor_overrides)
    metadata = _device_metadata(entry, sensor)

    device: dict[str, Any] = {
        "kind": kind,
        "role": role,
        "enabled": bool(entry.get("enabled", False)),
    }
    if identifier:
        device["identifier"] = identifier
    if serial_number:
        device["serial_number"] = serial_number
    elif kind == "realsense" and identifier:
        device["serial_number"] = identifier
    if device_path:
        device["device_path"] = device_path
    elif kind == "gelsight" and identifier:
        device["device_path"] = identifier
    if metadata.get("model") not in {"", None}:
        device["model"] = metadata["model"]
    for key in ("sensor_id", "attached_to", "mount_site", "calibration_ref"):
        value = metadata.get(key)
        if value not in {"", None}:
            device[key] = value
    return device


def _runtime_role_for_device(device: dict[str, Any]) -> str | None:
    if not bool(device.get("enabled", False)):
        return None
    role = str(device.get("role", "")).strip()
    if camera_path_parts_for_role(role) is not None or tactile_path_parts_for_role(role) is not None:
        return role
    return None


def _selected_topics_for_session(
    *,
    profile: dict[str, Any],
    devices: list[dict[str, Any]],
) -> list[str]:
    topics: set[str] = set()
    published = profile.get("published", {})
    enabled_roles = {role for role in (_runtime_role_for_device(device) for device in devices) if role}

    for arm_sources in published.get("observation_state", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    for arm_sources in published.get("action", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    teleop_activity_topic = str(profile.get("teleop_activity", {}).get("topic", "")).strip()
    if teleop_activity_topic:
        topics.add(teleop_activity_topic)

    for image_spec in published.get("images", []):
        topic = str(image_spec.get("topic", "")).strip()
        if not topic:
            continue
        role = sensor_role_for_topic(topic)
        if role is None or role in enabled_roles:
            topics.add(topic)

    for depth_spec in profile.get("published_depth", []):
        topic = str(depth_spec.get("topic", "")).strip()
        if not topic:
            continue
        role = sensor_role_for_topic(topic)
        if role is None or role in enabled_roles:
            topics.add(topic)

    for topic in profile.get("raw_only_topics", []):
        topic_str = str(topic).strip()
        if not topic_str:
            continue
        role = sensor_role_for_topic(topic_str)
        if role is None or role in enabled_roles:
            topics.add(topic_str)

    return sorted(topics)


def build_session_capture_plan(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    profile, _ = resolve_profile_for_active_arms("auto", active_arms)

    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}

    devices: list[dict[str, Any]] = []
    configured_session_devices = config.get("session_devices", [])
    for entry in configured_session_devices if isinstance(configured_session_devices, list) else []:
        if not isinstance(entry, dict):
            continue
        devices.append(
            _device_from_session_config(
                entry=entry,
                sensor_overrides=sensor_overrides,
            )
        )

    return {
        "schema_version": 3,
        "contract_version": "v2",
        "session_id": session_id,
        "active_arms": active_arms,
        "dataset_id": str(config.get("dataset_id", "")).strip(),
        "robot_type": str(config.get("robot_id", "")).strip(),
        "sensors_file": sensors_file or None,
        "devices": devices,
        "selected_topics": _selected_topics_for_session(profile=profile, devices=devices),
    }
