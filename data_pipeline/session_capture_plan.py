#!/usr/bin/env python3

"""Build the V2 session capture-plan object for the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_role,
    camera_topic_prefix_for_role,
    list_known_profiles,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    profile_compatibility_entry,
    resolve_profile_for_active_arms,
    sensor_role_for_topic,
    tactile_path_parts_for_role,
    tactile_topic_prefix_for_role,
)


def _overlay_status(path: str) -> dict[str, Any]:
    overlay_path = Path(path)
    return {
        "path": path,
        "exists": overlay_path.exists(),
        "kind": "local_defaults",
    }


def _clean_metadata(sensor: dict[str, Any]) -> dict[str, Any]:
    reserved = {
        "sensor_id",
        "attached_to",
        "mount_site",
        "serial_number",
        "model",
        "calibration_ref",
        "topic_names",
    }
    return {
        key: value
        for key, value in sensor.items()
        if key not in reserved and value not in {"", None}
    }


def _canonical_role_from_sensor_name(
    sensor_name: str,
    sensor: dict[str, Any],
    active_arms: list[str],
) -> str:
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


def _runtime_slot_for_device(device: dict[str, Any]) -> str | None:
    if not bool(device.get("enabled", False)):
        return None

    kind = str(device.get("kind", "")).strip()
    role = str(device.get("resolved_role", "")).strip()
    if kind == "realsense" and camera_topic_prefix_for_role(role):
        return role
    if kind == "gelsight" and tactile_topic_prefix_for_role(role):
        return role
    return None


def _selected_topics_for_session(
    *,
    profile: dict[str, Any],
    devices: list[dict[str, Any]],
    extra_topics: list[str],
) -> list[str]:
    topics: set[str] = set()
    published = profile.get("published", {})
    enabled_roles = {slot for slot in (_runtime_slot_for_device(device) for device in devices) if slot}

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

    for topic in extra_topics:
        if topic:
            topics.add(topic)

    return sorted(topics)


def _camera_device(
    *,
    device_kind: str,
    serial_number: str | None,
    enabled: bool,
    sensor_name: str,
    sensor: dict[str, Any],
    active_arms: list[str],
) -> dict[str, Any]:
    serial = str(serial_number or sensor.get("serial_number") or "").strip()
    role = _canonical_role_from_sensor_name(sensor_name, sensor, active_arms)
    device_id = f"{device_kind}/{serial}" if serial else f"{device_kind}/{role}"
    metadata = _clean_metadata(sensor)
    device = {
        "device_id": device_id,
        "kind": device_kind,
        "model": sensor.get("model"),
        "serial_number": serial or None,
        "enabled": enabled,
        "suggested_role": role,
        "resolved_role": role,
        "sensor_id": sensor.get("sensor_id"),
        "attached_to": sensor.get("attached_to"),
        "mount_site": sensor.get("mount_site"),
        "calibration_ref": sensor.get("calibration_ref"),
    }
    if metadata:
        device["metadata"] = metadata
    return device


def _device_from_session_config(
    *,
    entry: dict[str, Any],
    sensor_overrides: dict[str, dict[str, Any]],
    active_arms: list[str],
) -> dict[str, Any]:
    kind = str(entry.get("kind", "")).strip() or "device"
    overlay_key = str(entry.get("overlay_key", "")).strip()
    overlay_sensor = sensor_overrides.get(overlay_key, {}) if overlay_key else {}

    identifier = str(entry.get("identifier", "")).strip()
    serial_number = str(entry.get("serial_number", "")).strip()
    device_path = str(entry.get("device_path", "")).strip()
    if not serial_number and kind == "realsense":
        serial_number = identifier
    if not device_path and kind == "gelsight":
        device_path = identifier

    role = (
        str(entry.get("resolved_role", "")).strip()
        or str(entry.get("suggested_role", "")).strip()
        or _canonical_role_from_sensor_name(overlay_key or kind, overlay_sensor, active_arms)
    )

    merged_sensor = dict(overlay_sensor)
    for key in ("sensor_id", "attached_to", "mount_site", "model", "calibration_ref"):
        value = entry.get(key)
        if value not in {"", None}:
            merged_sensor[key] = value
    if serial_number:
        merged_sensor["serial_number"] = serial_number

    base = _camera_device(
        device_kind=kind,
        serial_number=serial_number or overlay_sensor.get("serial_number"),
        enabled=bool(entry.get("enabled", False)),
        sensor_name=overlay_key or kind,
        sensor=merged_sensor,
        active_arms=active_arms,
    )
    base["suggested_role"] = str(entry.get("suggested_role", "")).strip() or base["suggested_role"]
    base["resolved_role"] = role
    base["device_id"] = str(entry.get("device_id", "")).strip() or base["device_id"]
    if identifier:
        base["identifier"] = identifier
    if device_path:
        base["device_path"] = device_path
    if overlay_key:
        base["overlay_key"] = overlay_key
    source = str(entry.get("source", "")).strip()
    if source:
        base["source"] = source
    return base


def _expected_kind_for_role(role: str) -> str | None:
    if camera_path_parts_for_role(role) is not None:
        return "realsense"
    if tactile_path_parts_for_role(role) is not None:
        return "gelsight"
    return None


def _expected_devices_from_config(
    *,
    config: dict[str, Any],
    sensor_overrides: dict[str, dict[str, Any]],
    active_arms: list[str],
) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    configured = config.get("expected_session_devices", [])
    seen_keys: set[tuple[str, str, str]] = set()

    for index, entry in enumerate(configured if isinstance(configured, list) else []):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("resolved_role", "")).strip() or str(entry.get("suggested_role", "")).strip()
        kind = str(entry.get("kind", "")).strip() or _expected_kind_for_role(role) or "device"
        if not role:
            continue
        preferred_identifier = (
            str(entry.get("serial_number", "")).strip()
            or str(entry.get("device_path", "")).strip()
            or str(entry.get("identifier", "")).strip()
        )
        key = (kind, role, preferred_identifier)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        expected.append(
            {
                "expected_id": f"preset/{role}/{index}",
                "kind": kind,
                "expected_role": role,
                "preferred_identifier": preferred_identifier,
                "required": bool(entry.get("enabled", False)),
                "source": str(entry.get("source", "")).strip() or "preset",
            }
        )

    for sensor_name, sensor in sensor_overrides.items():
        if not bool(sensor.get("enabled_by_default", False)):
            continue
        role = _canonical_role_from_sensor_name(sensor_name, sensor, active_arms)
        kind = _expected_kind_for_role(role)
        if kind is None:
            continue
        preferred_identifier = str(sensor.get("serial_number", "")).strip()
        key = (kind, role, preferred_identifier)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        expected.append(
            {
                "expected_id": f"overlay/{role}",
                "kind": kind,
                "expected_role": role,
                "preferred_identifier": preferred_identifier,
                "required": True,
                "source": "overlay",
            }
        )
    return expected


def _device_matches_expected(device: dict[str, Any], expected: dict[str, Any]) -> bool:
    if str(device.get("kind", "")).strip() != str(expected.get("kind", "")).strip():
        return False

    preferred_identifier = str(expected.get("preferred_identifier", "")).strip()
    if preferred_identifier:
        candidate = (
            str(device.get("serial_number", "")).strip()
            or str(device.get("device_path", "")).strip()
            or str(device.get("identifier", "")).strip()
        )
        return candidate == preferred_identifier

    role = str(device.get("resolved_role", "")).strip() or str(device.get("suggested_role", "")).strip()
    return bool(role) and role == str(expected.get("expected_role", "")).strip()


def build_session_capture_plan(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    profile, profile_path = resolve_profile_for_active_arms("auto", active_arms)
    extra_topics = parse_task_list(str(config.get("extra_topics", "")))

    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}

    local_overlays = []
    if sensors_file:
        local_overlays.append(_overlay_status(sensors_file))

    devices: list[dict[str, Any]] = []

    configured_session_devices = config.get("session_devices", [])
    for entry in configured_session_devices if isinstance(configured_session_devices, list) else []:
        if not isinstance(entry, dict):
            continue
        devices.append(
            _device_from_session_config(
                entry=entry,
                sensor_overrides=sensor_overrides,
                active_arms=active_arms,
            )
        )

    expected_devices = _expected_devices_from_config(
        config=config,
        sensor_overrides=sensor_overrides,
        active_arms=active_arms,
    )
    matched_expected_ids = {
        str(expected.get("expected_id", "")).strip()
        for expected in expected_devices
        if any(_device_matches_expected(device, expected) for device in devices)
    }
    missing_expected_devices = [
        expected
        for expected in expected_devices
        if str(expected.get("expected_id", "")).strip() not in matched_expected_ids
    ]

    selected_topics = _selected_topics_for_session(
        profile=profile,
        devices=devices,
        extra_topics=extra_topics,
    )

    compatibility_entries = [
        profile_compatibility_entry(
            profile=known_profile,
            profile_path=known_profile_path,
            active_arms=active_arms,
            selected_topics=selected_topics,
        )
        for known_profile, known_profile_path in list_known_profiles()
    ]
    publishable_profiles = [entry for entry in compatibility_entries if entry["compatible"]]
    incompatible_profiles = [entry for entry in compatibility_entries if not entry["compatible"]]

    return {
        "schema_version": 2,
        "contract_version": "v2",
        "session_id": session_id,
        "active_arms": active_arms,
        "local_overlays": local_overlays,
        "default_published_profile": {
            "name": profile["profile_name"],
            "path": str(profile_path),
            "selection_rule": "auto_from_active_arms_v2",
        },
        "expected_devices": expected_devices,
        "missing_expected_devices": missing_expected_devices,
        "resolved_devices": devices,
        "discovered_devices": devices,
        "selected_topics": sorted(selected_topics),
        "selected_extra_topics": sorted(extra_topics),
        "profile_compatibility": {
            "publishable_profiles": publishable_profiles,
            "incompatible_profiles": incompatible_profiles,
        },
    }
