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
    role_choices_for_kind,
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
_REALSENSE_MODEL_HINTS = {
    "405": "Intel RealSense D405",
    "415": "Intel RealSense D415",
    "435": "Intel RealSense D435",
    "455": "Intel RealSense D455",
    "515": "Intel RealSense L515",
}


def _normalize_serial(value: str | None) -> str:
    normalized = str(value or "").strip().strip("'").strip('"').lower()
    if not normalized:
        return ""
    trimmed = normalized.lstrip("0")
    return trimmed or normalized


def _canonical_role_from_sensor(sensor_name: str, sensor: dict[str, Any]) -> str:
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


def _device_key(kind: str, identifier: str) -> tuple[str, str]:
    if kind == "realsense":
        return kind, _normalize_serial(identifier)
    return kind, identifier.strip().lower()


def _current_selection_map(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    selections: dict[tuple[str, str], dict[str, Any]] = {}
    devices = config.get("session_devices", [])
    for entry in devices if isinstance(devices, list) else []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).strip()
        identifier = (
            str(entry.get("serial_number", "")).strip()
            or str(entry.get("device_path", "")).strip()
            or str(entry.get("identifier", "")).strip()
        )
        role = str(entry.get("role", "")).strip()
        if not kind or not identifier:
            continue
        selections[_device_key(kind, identifier)] = {
            "enabled": bool(entry.get("enabled", False)),
            "role": role,
        }
    return selections


def _matched_sensor_for_realsense(
    serial_number: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized = _normalize_serial(serial_number)
    for sensor_name, sensor in sensor_overrides.items():
        if camera_path_parts_for_role(sensor_name) is None:
            continue
        if _normalize_serial(sensor.get("serial_number")) == normalized:
            return sensor_name, sensor
    return None, None


def _matched_sensor_for_gelsight(
    device_path: str,
    serial_number: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized_serial = _normalize_serial(serial_number)
    lowered_path = device_path.lower()
    for sensor_name, sensor in sensor_overrides.items():
        if tactile_path_parts_for_role(sensor_name) is None:
            continue
        sensor_serial = _normalize_serial(sensor.get("serial_number"))
        if sensor_serial and sensor_serial == normalized_serial:
            return sensor_name, sensor
        if sensor_serial and sensor_serial in lowered_path:
            return sensor_name, sensor
    return None, None


def _default_enabled(sensor: dict[str, Any] | None) -> bool:
    if not sensor:
        return False
    if "enabled_by_default" in sensor:
        return bool(sensor.get("enabled_by_default"))
    return True


def _role_from_selection_or_sensor(
    *,
    selection: dict[str, Any] | None,
    sensor_name: str | None,
    sensor: dict[str, Any] | None,
) -> str:
    if selection:
        role = str(selection.get("role", "")).strip()
        if role:
            return role
    if sensor_name and sensor:
        return _canonical_role_from_sensor(sensor_name, sensor)
    return ""


def _device_entry(
    *,
    kind: str,
    model: str,
    identifier: str,
    role: str,
    enabled: bool,
    serial_number: str = "",
    device_path: str = "",
    sensor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": kind,
        "model": model,
        "identifier": identifier,
        "role": role,
        "enabled": enabled,
    }
    if serial_number:
        entry["serial_number"] = serial_number
    if device_path:
        entry["device_path"] = device_path
    if sensor:
        for key in ("sensor_id", "attached_to", "mount_site", "calibration_ref"):
            value = sensor.get(key)
            if value not in {"", None}:
                entry[key] = value
    return entry


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
        model = _REALSENSE_MODEL_HINTS.get(model_suffix, "Intel RealSense")

        discovered.append(
            {
                "kind": "realsense",
                "identifier": raw_serial,
                "serial_number": raw_serial,
                "model": model,
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
            }
        )
    return discovered


def _looks_like_gelsight(path: str, sensor_overrides: dict[str, dict[str, Any]]) -> bool:
    lowered = Path(path).name.lower()
    if "gelsight" in lowered or "arducam" in lowered:
        return True
    for sensor in sensor_overrides.values():
        sensor_serial = _normalize_serial(sensor.get("serial_number"))
        if sensor_serial and sensor_serial in lowered:
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
            }
        )
    return discovered


def _heuristic_camera_role(model: str, used_roles: set[str], active_arms: list[str]) -> str:
    primary_arm = active_arms[0] if active_arms else "lightning"
    wrist_role = f"{primary_arm}_wrist_1"
    if "405" in model and wrist_role not in used_roles:
        return wrist_role
    for role in role_choices_for_kind("realsense"):
        if role.startswith("scene_") and role not in used_roles:
            return role
    return "scene_1"


def _heuristic_tactile_role(used_roles: set[str], active_arms: list[str]) -> str:
    primary_arm = active_arms[0] if active_arms else "lightning"
    for role in (f"{primary_arm}_finger_left", f"{primary_arm}_finger_right"):
        if role not in used_roles:
            return role
    return f"{primary_arm}_finger_left"


def discover_session_devices(config: dict[str, Any]) -> list[dict[str, Any]]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}
    current_selections = _current_selection_map(config)

    devices: list[dict[str, Any]] = []
    used_roles: set[str] = set()

    realsense_cameras = _discover_realsense_sdk() or _discover_realsense_v4l()
    for camera in realsense_cameras:
        serial_number = str(camera.get("serial_number", "")).strip()
        selection = current_selections.get(_device_key("realsense", serial_number))
        sensor_name, sensor = _matched_sensor_for_realsense(serial_number, sensor_overrides)
        role = _role_from_selection_or_sensor(selection=selection, sensor_name=sensor_name, sensor=sensor)
        if not role:
            role = _heuristic_camera_role(str(camera.get("model", "")), used_roles, active_arms)
        used_roles.add(role)
        enabled = selection["enabled"] if selection is not None else _default_enabled(sensor)
        devices.append(
            _device_entry(
                kind="realsense",
                model=str(camera.get("model", "")).strip() or "Intel RealSense",
                identifier=serial_number,
                serial_number=serial_number,
                role=role,
                enabled=enabled,
                sensor=sensor,
            )
        )

    for tactile in _discover_gelsight_v4l(sensor_overrides):
        device_path = str(tactile.get("device_path", "")).strip()
        serial_number = str(tactile.get("serial_number", "")).strip()
        selection = current_selections.get(_device_key("gelsight", device_path))
        sensor_name, sensor = _matched_sensor_for_gelsight(device_path, serial_number, sensor_overrides)
        role = _role_from_selection_or_sensor(selection=selection, sensor_name=sensor_name, sensor=sensor)
        if not role:
            role = _heuristic_tactile_role(used_roles, active_arms)
        used_roles.add(role)
        enabled = selection["enabled"] if selection is not None else _default_enabled(sensor)
        devices.append(
            _device_entry(
                kind="gelsight",
                model=str(tactile.get("model", "")).strip() or "GelSight Mini",
                identifier=device_path,
                device_path=device_path,
                serial_number=serial_number,
                role=role,
                enabled=enabled,
                sensor=sensor,
            )
        )

    return devices
