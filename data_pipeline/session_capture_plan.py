#!/usr/bin/env python3

"""Build the transitional session capture-plan object for the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    collect_candidate_topics,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
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


def build_session_capture_plan(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    profile, profile_path = resolve_profile_for_active_arms("auto", active_arms)
    extra_topics = parse_task_list(str(config.get("extra_topics", "")))
    planned_topics = collect_candidate_topics(profile)
    for topic in extra_topics:
        if topic not in planned_topics:
            planned_topics.append(topic)

    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}

    local_overlays = []
    if sensors_file:
        local_overlays.append(_overlay_status(sensors_file))

    devices = _arm_devices(active_arms)

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
            devices.append(
                _camera_device(
                    device_kind="gelsight",
                    serial_number=str(sensor_overrides.get("left", {}).get("serial_number", "")).strip() or None,
                    enabled=True,
                    sensor_name="left",
                    sensor=sensor_overrides.get("left", {}),
                    active_arms=active_arms,
                )
            )
        if bool(config.get("gelsight_enable_right", False)):
            devices.append(
                _camera_device(
                    device_kind="gelsight",
                    serial_number=str(sensor_overrides.get("right", {}).get("serial_number", "")).strip() or None,
                    enabled=True,
                    sensor_name="right",
                    sensor=sensor_overrides.get("right", {}),
                    active_arms=active_arms,
                )
            )

    return {
        "schema_version": 1,
        "contract_version": "v1",
        "session_id": session_id,
        "active_arms": active_arms,
        "local_overlays": local_overlays,
        "resolved_devices": devices,
        "planned_topics": sorted(planned_topics),
        "profile_compatibility": {
            "publishable_profiles": [
                {
                    "name": profile["profile_name"],
                    "path": str(profile_path),
                    "compatible": True,
                }
            ],
            "incompatible_profiles": [],
        },
    }
