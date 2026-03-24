#!/usr/bin/env python3

"""Build the transitional session capture-plan object for the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    list_known_profiles,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    profile_compatibility_entry,
    resolve_profile_for_active_arms,
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


def _topic_sensor_slot(topic: str) -> str | None:
    if topic.startswith("/spark/cameras/wrist/"):
        return "wrist"
    if topic.startswith("/spark/cameras/scene/"):
        return "scene"
    if topic.startswith("/spark/tactile/left/"):
        return "left"
    if topic.startswith("/spark/tactile/right/"):
        return "right"
    return None


def _canonical_role_from_sensor_name(
    sensor_name: str,
    sensor: dict[str, Any],
    active_arms: list[str],
) -> str:
    attached_to = str(sensor.get("attached_to", "")).strip()
    mount_site = str(sensor.get("mount_site", "")).strip()

    if mount_site.startswith("scene_"):
        return mount_site
    if mount_site == "wrist" and attached_to:
        return f"{attached_to}_wrist_0"
    if mount_site.startswith("finger_") and attached_to:
        return f"{attached_to}_{mount_site}"

    primary_arm = active_arms[0] if active_arms else "lightning"
    if sensor_name == "wrist":
        if len(active_arms) == 1:
            return f"{primary_arm}_wrist_0"
        return "wrist_0_unassigned"
    if sensor_name == "scene":
        return "scene_0"
    if sensor_name == "left":
        return f"{primary_arm}_finger_left"
    if sensor_name == "right":
        return f"{primary_arm}_finger_right"
    return sensor_name


def _arm_devices(active_arms: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "device_id": f"arm/{arm}",
            "kind": "ur_arm",
            "enabled": True,
            "suggested_role": arm,
            "resolved_role": arm,
        }
        for arm in active_arms
    ]


def _runtime_slot_for_device(device: dict[str, Any]) -> str | None:
    if not bool(device.get("enabled", False)):
        return None

    kind = str(device.get("kind", "")).strip()
    role = str(device.get("resolved_role", "")).strip()
    if kind == "realsense":
        if role.startswith("scene_"):
            return "scene"
        if "_wrist_" in role:
            return "wrist"
    if kind == "gelsight":
        if role.endswith("finger_left"):
            return "left"
        if role.endswith("finger_right"):
            return "right"
    return None


def _primary_realsense_roles(devices: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    primary_wrist_role: str | None = None
    primary_scene_role: str | None = None
    for device in devices:
        if not bool(device.get("enabled", False)):
            continue
        if str(device.get("kind", "")).strip() != "realsense":
            continue
        role = str(device.get("resolved_role", "")).strip()
        if primary_wrist_role is None and "_wrist_" in role:
            primary_wrist_role = role
            continue
        if primary_scene_role is None and role.startswith("scene_"):
            primary_scene_role = role
    return primary_wrist_role, primary_scene_role


def realsense_camera_name_for_device(
    device: dict[str, Any],
    *,
    primary_wrist_role: str | None,
    primary_scene_role: str | None,
) -> str:
    role = str(device.get("resolved_role", "")).strip()
    if role and role == primary_wrist_role:
        return "wrist"
    if role and role == primary_scene_role:
        return "scene"
    return role or "camera"


def realsense_launch_plan(devices: list[dict[str, Any]]) -> dict[str, Any]:
    primary_wrist_role, primary_scene_role = _primary_realsense_roles(devices)
    wrist_serial = ""
    scene_serial = ""
    extra_camera_specs: list[str] = []
    launched_cameras: list[dict[str, str]] = []

    for device in devices:
        if not bool(device.get("enabled", False)):
            continue
        if str(device.get("kind", "")).strip() != "realsense":
            continue
        serial_number = (
            str(device.get("serial_number", "")).strip()
            or str(device.get("identifier", "")).strip()
        )
        if not serial_number:
            continue
        camera_name = realsense_camera_name_for_device(
            device,
            primary_wrist_role=primary_wrist_role,
            primary_scene_role=primary_scene_role,
        )
        launched_cameras.append(
            {
                "camera_name": camera_name,
                "serial_number": serial_number,
                "color_profile": "640,480,30",
                "depth_profile": "640,480,30",
            }
        )
        if camera_name == "wrist" and not wrist_serial:
            wrist_serial = serial_number
            continue
        if camera_name == "scene" and not scene_serial:
            scene_serial = serial_number
            continue
        extra_camera_specs.append(f"{camera_name};{serial_number};640,480,30;640,480,30")

    return {
        "wrist_serial_no": wrist_serial,
        "scene_serial_no": scene_serial,
        "extra_camera_specs": extra_camera_specs,
        "cameras": launched_cameras,
    }


def session_sensor_topics(devices: list[dict[str, Any]]) -> list[str]:
    topics: set[str] = set()
    launch_plan = realsense_launch_plan(devices)
    for camera in launch_plan["cameras"]:
        prefix = f"/spark/cameras/{camera['camera_name']}"
        topics.add(prefix + "/color/image_raw")
        topics.add(prefix + "/depth/image_rect_raw")

    for device in devices:
        if not bool(device.get("enabled", False)):
            continue
        if str(device.get("kind", "")).strip() != "gelsight":
            continue
        role = str(device.get("resolved_role", "")).strip()
        if role.endswith("finger_left"):
            prefix = "/spark/tactile/left"
        elif role.endswith("finger_right"):
            prefix = "/spark/tactile/right"
        else:
            continue
        topics.add(prefix + "/color/image_raw")
        topics.add(prefix + "/depth/image_raw")
        topics.add(prefix + "/marker_offset")

    return sorted(topics)


def _selected_topics_for_session(
    *,
    profile: dict[str, Any],
    devices: list[dict[str, Any]],
    extra_topics: list[str],
) -> list[str]:
    topics: set[str] = set()
    published = profile.get("published", {})
    enabled_slots = {slot for slot in (_runtime_slot_for_device(device) for device in devices) if slot}

    for arm_sources in published.get("observation_state", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    for arm_sources in published.get("action", {}).get("sources", {}).values():
        topics.update(arm_sources.values())

    teleop_activity_topic = str(profile.get("teleop_activity", {}).get("topic", "")).strip()
    if teleop_activity_topic:
        topics.add(teleop_activity_topic)

    topics.update(session_sensor_topics(devices))

    for topic in profile.get("raw_only_topics", []):
        topic_str = str(topic).strip()
        if not topic_str:
            continue
        slot = _topic_sensor_slot(topic_str)
        if slot is None or slot in enabled_slots:
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


def build_session_capture_plan(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    profile, profile_path = resolve_profile_for_active_arms("auto", active_arms)
    extra_topics = parse_task_list(str(config.get("extra_topics", "")))

    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}

    local_overlays = []
    if sensors_file:
        local_overlays.append(_overlay_status(sensors_file))

    devices = _arm_devices(active_arms)

    configured_session_devices = config.get("session_devices", [])
    if isinstance(configured_session_devices, list) and configured_session_devices:
        for entry in configured_session_devices:
            if not isinstance(entry, dict):
                continue
            devices.append(
                _device_from_session_config(
                    entry=entry,
                    sensor_overrides=sensor_overrides,
                    active_arms=active_arms,
                )
            )
    else:
        if bool(config.get("realsense_enabled", True)):
            wrist_serial = str(config.get("wrist_serial_no", "")).strip()
            if wrist_serial:
                devices.append(
                    _camera_device(
                        device_kind="realsense",
                        serial_number=wrist_serial,
                        enabled=True,
                        sensor_name="wrist",
                        sensor=sensor_overrides.get("wrist", {}),
                        active_arms=active_arms,
                    )
                )
            scene_serial = str(config.get("scene_serial_no", "")).strip()
            if scene_serial:
                devices.append(
                    _camera_device(
                        device_kind="realsense",
                        serial_number=scene_serial,
                        enabled=True,
                        sensor_name="scene",
                        sensor=sensor_overrides.get("scene", {}),
                        active_arms=active_arms,
                    )
                )

        if bool(config.get("gelsight_enabled", False)):
            if bool(config.get("gelsight_enable_left", False)):
                left_sensor = dict(sensor_overrides.get("left", {}))
                left_path = str(config.get("gelsight_left_device_path", "")).strip()
                if left_path:
                    left_sensor["device_path"] = left_path
                devices.append(
                    _camera_device(
                        device_kind="gelsight",
                        serial_number=str(left_sensor.get("serial_number", "")).strip() or None,
                        enabled=True,
                        sensor_name="left",
                        sensor=left_sensor,
                        active_arms=active_arms,
                    )
                )
            if bool(config.get("gelsight_enable_right", False)):
                right_sensor = dict(sensor_overrides.get("right", {}))
                right_path = str(config.get("gelsight_right_device_path", "")).strip()
                if right_path:
                    right_sensor["device_path"] = right_path
                devices.append(
                    _camera_device(
                        device_kind="gelsight",
                        serial_number=str(right_sensor.get("serial_number", "")).strip() or None,
                        enabled=True,
                        sensor_name="right",
                        sensor=right_sensor,
                        active_arms=active_arms,
                    )
                )

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
        "schema_version": 1,
        "contract_version": "v1",
        "session_id": session_id,
        "active_arms": active_arms,
        "local_overlays": local_overlays,
        "default_published_profile": {
            "name": profile["profile_name"],
            "path": str(profile_path),
            "selection_rule": "auto_from_active_arms_v1",
        },
        "discovered_devices": devices,
        "selected_topics": sorted(selected_topics),
        "selected_extra_topics": sorted(extra_topics),
        "profile_compatibility": {
            "publishable_profiles": publishable_profiles,
            "incompatible_profiles": incompatible_profiles,
        },
    }
