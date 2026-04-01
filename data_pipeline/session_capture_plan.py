#!/usr/bin/env python3

"""Build the V2 session profile object used by the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_sensor_key,
    canonical_sensor_key,
    collect_candidate_topics,
    effective_profile_for_session,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    resolve_profile_for_active_arms,
    tactile_path_parts_for_sensor_key,
)


def _canonical_sensor_key_from_sensor_name(sensor_name: str, sensor: dict[str, Any]) -> str:
    sensor_key = str(sensor.get("sensor_key", "")).strip() or str(sensor_name).strip()
    return canonical_sensor_key(sensor_key)


def _sensor_for_sensor_key(
    sensor_key: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any]]:
    sensor_key_str = canonical_sensor_key(sensor_key)
    if not sensor_key_str:
        return None, {}
    for sensor_name, sensor in sensor_overrides.items():
        if _canonical_sensor_key_from_sensor_name(sensor_name, sensor) == sensor_key_str:
            return sensor_name, sensor
    return None, {}


def _device_metadata(entry: dict[str, Any], sensor: dict[str, Any]) -> dict[str, Any]:
    merged = dict(sensor)
    return merged


def _device_from_session_config(
    *,
    entry: dict[str, Any],
    sensor_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    kind = str(entry.get("kind", "")).strip() or "device"
    sensor_key = canonical_sensor_key(str(entry.get("sensor_key", "")).strip())
    serial_number = str(entry.get("serial_number", "")).strip()
    device_path = str(entry.get("device_path", "")).strip()

    _sensor_name, sensor = _sensor_for_sensor_key(sensor_key, sensor_overrides)
    metadata = _device_metadata(entry, sensor)

    device: dict[str, Any] = {
        "kind": kind,
        "sensor_key": sensor_key,
        "enabled": bool(entry.get("enabled", False)),
    }
    if serial_number:
        device["serial_number"] = serial_number
    if device_path:
        device["device_path"] = device_path
    return device


def _runtime_sensor_key_for_device(device: dict[str, Any]) -> str | None:
    if not bool(device.get("enabled", False)):
        return None
    sensor_key = canonical_sensor_key(str(device.get("sensor_key", "")).strip())
    if camera_path_parts_for_sensor_key(sensor_key) is not None or tactile_path_parts_for_sensor_key(sensor_key) is not None:
        return sensor_key
    return None


def _selected_topics_for_session(
    *,
    effective_profile: dict[str, Any],
) -> list[str]:
    return collect_candidate_topics(effective_profile)


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

    enabled_sensor_keys = [
        sensor_key
        for sensor_key in (_runtime_sensor_key_for_device(device) for device in devices)
        if sensor_key
    ]
    effective_profile = effective_profile_for_session(profile, active_arms, enabled_sensor_keys)

    return {
        "schema_version": 4,
        "contract_version": "v2",
        "session_id": session_id,
        "active_arms": active_arms,
        "sensors_file": sensors_file or None,
        "devices": devices,
        "selected_topics": _selected_topics_for_session(effective_profile=effective_profile),
    }
