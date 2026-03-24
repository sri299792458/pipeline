#!/usr/bin/env python3

"""Runtime device discovery helpers for the operator console."""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_role,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    tactile_path_parts_for_role,
)

try:
    import pyrealsense2 as rs
except Exception:  # pragma: no cover - optional runtime dependency
    rs = None


_V4L_DIR = "/dev/v4l/by-id"
_VIDEO_INDEX0_GLOB = f"{_V4L_DIR}/*-video-index0"
_SERIAL_SUFFIX_PATTERN = re.compile(r"_([^_]+)-video-index\d+$")
_REALSENSE_MODEL_PATTERN = re.compile(r"RealSense_TM__(?:Depth_Camera|Camera)_([0-9]+)")


def _normalize_serial(value: str | None) -> str:
    normalized = str(value or "").strip().strip("'").strip('"').lower()
    if not normalized:
        return ""
    trimmed = normalized.lstrip("0")
    return trimmed or normalized


def _canonical_role_from_sensor(sensor_name: str, sensor: dict[str, Any], active_arms: list[str]) -> str:
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


def _enabled_roles(config: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    seed_devices = config.get("discovery_seed_devices", config.get("session_devices", []))
    for entry in seed_devices if isinstance(seed_devices, list) else []:
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("enabled", False)):
            role = str(entry.get("resolved_role", "")).strip() or str(entry.get("suggested_role", "")).strip()
            if role:
                roles.add(role)
    return roles


def _expected_kind_for_role(role: str) -> str | None:
    if camera_path_parts_for_role(role) is not None:
        return "realsense"
    if tactile_path_parts_for_role(role) is not None:
        return "gelsight"
    return None


def _expected_identifier(entry: dict[str, Any]) -> str:
    return (
        str(entry.get("serial_number", "")).strip()
        or str(entry.get("device_path", "")).strip()
        or str(entry.get("identifier", "")).strip()
    )


def _normalize_expected_identifier(kind: str, identifier: str) -> str:
    if kind == "realsense":
        return _normalize_serial(identifier)
    return identifier.strip().lower()


def _normalized_device_identifier(device: dict[str, Any]) -> str:
    kind = str(device.get("kind", "")).strip()
    if kind == "realsense":
        return _normalize_serial(
            str(device.get("serial_number", "")).strip() or str(device.get("identifier", "")).strip()
        )
    return (
        str(device.get("device_path", "")).strip().lower()
        or str(device.get("identifier", "")).strip().lower()
        or _normalize_serial(str(device.get("serial_number", "")).strip())
    )


def _expected_devices_from_config(
    config: dict[str, Any],
    sensor_overrides: dict[str, dict[str, Any]],
    active_arms: list[str],
) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    configured = config.get("expected_session_devices", [])
    for index, entry in enumerate(configured if isinstance(configured, list) else []):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("resolved_role", "")).strip() or str(entry.get("suggested_role", "")).strip()
        kind = str(entry.get("kind", "")).strip() or _expected_kind_for_role(role) or "device"
        if not role:
            continue
        preferred_identifier = _expected_identifier(entry)
        key = (kind, role, _normalize_expected_identifier(kind, preferred_identifier))
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
        role = _canonical_role_from_sensor(sensor_name, sensor, active_arms)
        kind = _expected_kind_for_role(role)
        if kind is None:
            continue
        preferred_identifier = str(sensor.get("serial_number", "")).strip()
        key = (kind, role, _normalize_expected_identifier(kind, preferred_identifier))
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

    expected_identifier = _normalize_expected_identifier(
        str(expected.get("kind", "")).strip(),
        str(expected.get("preferred_identifier", "")).strip(),
    )
    if expected_identifier:
        return _normalized_device_identifier(device) == expected_identifier

    role = str(device.get("resolved_role", "")).strip() or str(device.get("suggested_role", "")).strip()
    return bool(role) and role == str(expected.get("expected_role", "")).strip()


def _match_label(match_sources: list[str]) -> str:
    unique = []
    for source in match_sources:
        if source not in unique:
            unique.append(source)
    if not unique:
        return "unmatched"
    return " + ".join(unique)


def _overlay_entry_from_sensor(
    *,
    sensor_name: str,
    sensor: dict[str, Any],
    kind: str,
    identifier: str,
    active_arms: list[str],
    enabled: bool,
    source: str,
) -> dict[str, Any]:
    role = _canonical_role_from_sensor(sensor_name, sensor, active_arms)
    entry: dict[str, Any] = {
        "kind": kind,
        "identifier": identifier,
        "enabled": enabled,
        "suggested_role": role,
        "resolved_role": role,
        "overlay_key": sensor_name,
        "source": source,
    }
    for key in ("model", "sensor_id", "attached_to", "mount_site", "calibration_ref"):
        value = sensor.get(key)
        if value not in {"", None}:
            entry[key] = value
    if kind == "realsense":
        entry["serial_number"] = identifier
    else:
        entry["device_path"] = identifier
        serial_number = str(sensor.get("serial_number", "")).strip()
        if serial_number:
            entry["serial_number"] = serial_number
    return entry


def _matched_overlay_for_realsense(serial_number: str, sensor_overrides: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized = _normalize_serial(serial_number)
    for sensor_name, sensor in sensor_overrides.items():
        if camera_path_parts_for_role(sensor_name) is None:
            continue
        if _normalize_serial(sensor.get("serial_number")) == normalized:
            return sensor_name, sensor
    return None, None


def _matched_overlay_for_gelsight(
    device_path: str,
    serial_number: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized_serial = _normalize_serial(serial_number)
    path_lower = device_path.lower()
    for sensor_name, sensor in sensor_overrides.items():
        if tactile_path_parts_for_role(sensor_name) is None:
            continue
        overlay_serial = _normalize_serial(sensor.get("serial_number"))
        if overlay_serial and overlay_serial == normalized_serial:
            return sensor_name, sensor
        if overlay_serial and overlay_serial in path_lower:
            return sensor_name, sensor
    return None, None


def _discover_realsense_v4l() -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_serials: set[str] = set()
    for path in sorted(glob.glob(_VIDEO_INDEX0_GLOB)):
        name = Path(path).name
        if "RealSense" not in name:
            continue
        serial_match = _SERIAL_SUFFIX_PATTERN.search(name)
        if not serial_match:
            continue
        raw_serial = serial_match.group(1)
        normalized = _normalize_serial(raw_serial)
        if not normalized or normalized in seen_serials:
            continue
        seen_serials.add(normalized)

        model_match = _REALSENSE_MODEL_PATTERN.search(name)
        model_suffix = model_match.group(1) if model_match else ""
        model = f"Intel RealSense D{model_suffix}" if model_suffix in {"405", "415", "435", "455"} else (
            f"Intel RealSense L{model_suffix}" if model_suffix == "515" else "Intel RealSense"
        )

        discovered.append(
            {
                "kind": "realsense",
                "identifier": raw_serial,
                "serial_number": raw_serial,
                "model": model,
                "path": path,
            }
        )
    return discovered


def _discover_realsense_sdk() -> list[dict[str, Any]]:
    if rs is None:
        return []

    discovered: list[dict[str, Any]] = []
    seen_serials: set[str] = set()
    context = rs.context()
    for device in context.query_devices():
        try:
            serial_number = device.get_info(rs.camera_info.serial_number)
        except Exception:
            continue
        normalized = _normalize_serial(serial_number)
        if not normalized or normalized in seen_serials:
            continue
        seen_serials.add(normalized)

        try:
            model = device.get_info(rs.camera_info.name)
        except Exception:
            model = "Intel RealSense"

        discovered.append(
            {
                "kind": "realsense",
                "identifier": serial_number,
                "serial_number": serial_number,
                "model": model,
                "path": "",
            }
        )
    return discovered


def _looks_like_gelsight(path: str, sensor_overrides: dict[str, dict[str, Any]]) -> bool:
    lowered = Path(path).name.lower()
    if "gelsight" in lowered:
        return True
    if "arducam" in lowered:
        return True
    for sensor in sensor_overrides.values():
        overlay_serial = _normalize_serial(sensor.get("serial_number"))
        if overlay_serial and overlay_serial in lowered:
            return True
    return False


def _discover_gelsight_v4l(sensor_overrides: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    for path in sorted(glob.glob(_VIDEO_INDEX0_GLOB)):
        name = Path(path).name
        if "RealSense" in name:
            continue
        if not _looks_like_gelsight(path, sensor_overrides):
            continue
        serial_match = _SERIAL_SUFFIX_PATTERN.search(name)
        raw_serial = serial_match.group(1) if serial_match else ""
        discovered.append(
            {
                "kind": "gelsight",
                "identifier": path,
                "device_path": path,
                "serial_number": raw_serial or "",
                "model": "GelSight Mini" if "gelsight" in name.lower() else "Tactile Camera",
                "path": path,
            }
        )
    return discovered


def discover_session_devices(config: dict[str, Any]) -> list[dict[str, Any]]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}
    enabled_roles = _enabled_roles(config)

    devices: list[dict[str, Any]] = []
    used_roles: set[str] = set()

    realsense_cameras = _discover_realsense_sdk() or _discover_realsense_v4l()
    for camera in realsense_cameras:
        primary_arm = active_arms[0] if active_arms else "lightning"
        sensor_name, sensor = _matched_overlay_for_realsense(camera["serial_number"], sensor_overrides)
        if sensor_name and sensor is not None:
            entry = _overlay_entry_from_sensor(
                sensor_name=sensor_name,
                sensor=sensor,
                kind="realsense",
                identifier=camera["serial_number"],
                active_arms=active_arms,
                enabled=_canonical_role_from_sensor(sensor_name, sensor, active_arms) in enabled_roles,
                source="discovered",
            )
            entry["model"] = camera["model"]
            used_roles.add(str(entry["resolved_role"]))
            devices.append(entry)
            continue

        if f"{primary_arm}_wrist_1" not in used_roles and " 405" in f" {camera['model']}":
            suggested_role = f"{primary_arm}_wrist_1"
        else:
            scene_index = 1
            while f"scene_{scene_index}" in used_roles:
                scene_index += 1
            suggested_role = f"scene_{scene_index}"

        used_roles.add(suggested_role)
        devices.append(
            {
                "kind": "realsense",
                "identifier": camera["serial_number"],
                "serial_number": camera["serial_number"],
                "enabled": False,
                "suggested_role": suggested_role,
                "resolved_role": suggested_role,
                "overlay_key": "",
                "source": "discovered",
                "model": camera["model"],
            }
        )

    for tactile in _discover_gelsight_v4l(sensor_overrides):
        primary_arm = active_arms[0] if active_arms else "lightning"
        sensor_name, sensor = _matched_overlay_for_gelsight(
            tactile["device_path"],
            tactile["serial_number"],
            sensor_overrides,
        )
        if sensor_name and sensor is not None:
            entry = _overlay_entry_from_sensor(
                sensor_name=sensor_name,
                sensor=sensor,
                kind="gelsight",
                identifier=tactile["device_path"],
                active_arms=active_arms,
                enabled=_canonical_role_from_sensor(sensor_name, sensor, active_arms) in enabled_roles,
                source="discovered",
            )
            entry["model"] = tactile["model"]
            used_roles.add(str(entry["resolved_role"]))
            devices.append(entry)
            continue

        candidate_roles = [f"{primary_arm}_finger_left", f"{primary_arm}_finger_right"]
        suggested_role = next((role for role in candidate_roles if role not in used_roles), candidate_roles[0])
        used_roles.add(suggested_role)
        devices.append(
            {
                "kind": "gelsight",
                "identifier": tactile["device_path"],
                "device_path": tactile["device_path"],
                "serial_number": tactile["serial_number"],
                "enabled": False,
                "suggested_role": suggested_role,
                "resolved_role": suggested_role,
                "overlay_key": "",
                "source": "discovered",
                "model": tactile["model"],
            }
        )

    return devices


def discover_session_inventory(config: dict[str, Any]) -> dict[str, Any]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}

    discovered_devices = discover_session_devices(config)
    expected_devices = _expected_devices_from_config(config, sensor_overrides, active_arms)

    matched_expected_ids: set[str] = set()
    for device in discovered_devices:
        match_sources: list[str] = []
        if str(device.get("overlay_key", "")).strip():
            match_sources.append("overlay")
        for expected in expected_devices:
            if _device_matches_expected(device, expected):
                matched_expected_ids.add(str(expected.get("expected_id", "")).strip())
                source = str(expected.get("source", "")).strip()
                if source:
                    match_sources.append(source)
        device["match_sources"] = list(dict.fromkeys(match_sources))
        device["match_label"] = _match_label(match_sources)

    missing_expected_devices = [
        expected
        for expected in expected_devices
        if str(expected.get("expected_id", "")).strip() not in matched_expected_ids
    ]

    return {
        "discovered_devices": discovered_devices,
        "expected_devices": expected_devices,
        "missing_expected_devices": missing_expected_devices,
    }
