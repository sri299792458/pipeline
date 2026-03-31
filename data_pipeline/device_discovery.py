#!/usr/bin/env python3

"""Runtime device discovery helpers for the operator console."""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_sensor_key,
    canonical_sensor_key,
    load_optional_sensor_overrides,
    normalize_active_arms,
    parse_task_list,
    sensor_key_choices_for_kind,
    tactile_path_parts_for_sensor_key,
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


def _canonical_sensor_key_from_sensor(sensor_name: str, sensor: dict[str, Any]) -> str:
    sensor_key = str(sensor.get("sensor_key", "")).strip() or str(sensor_name).strip()
    return canonical_sensor_key(sensor_key)


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
        )
        sensor_key = canonical_sensor_key(str(entry.get("sensor_key", "")).strip())
        if not kind or not identifier:
            continue
        selections[_device_key(kind, identifier)] = {
            "enabled": bool(entry.get("enabled", False)),
            "sensor_key": sensor_key,
        }
    return selections


def _matched_sensor_for_realsense(
    serial_number: str,
    sensor_overrides: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized = _normalize_serial(serial_number)
    for sensor_name, sensor in sensor_overrides.items():
        if camera_path_parts_for_sensor_key(sensor_name) is None:
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
        if tactile_path_parts_for_sensor_key(sensor_name) is None:
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


def _sensor_key_from_selection_or_sensor(
    *,
    selection: dict[str, Any] | None,
    sensor_name: str | None,
    sensor: dict[str, Any] | None,
) -> str:
    if selection:
        sensor_key = canonical_sensor_key(str(selection.get("sensor_key", "")).strip())
        if sensor_key:
            return sensor_key
    if sensor_name and sensor:
        return _canonical_sensor_key_from_sensor(sensor_name, sensor)
    return ""


def _device_entry(
    *,
    kind: str,
    model: str,
    sensor_key: str,
    enabled: bool,
    serial_number: str = "",
    device_path: str = "",
    sensor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": kind,
        "model": model,
        "sensor_key": canonical_sensor_key(sensor_key),
        "enabled": enabled,
    }
    if serial_number:
        entry["serial_number"] = serial_number
    if device_path:
        entry["device_path"] = device_path
    if sensor:
        for key in ("calibration_ref",):
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
                "device_path": path,
                "serial_number": raw_serial or "",
                "model": "GelSight Mini" if "gelsight" in name.lower() else "Tactile Camera",
            }
        )
    return discovered


def _heuristic_camera_sensor_key(model: str, used_sensor_keys: set[str], active_arms: list[str]) -> str:
    primary_arm = active_arms[0] if active_arms else "lightning"
    wrist_sensor_key = f"/spark/cameras/{primary_arm}/wrist_1"
    if "405" in model and wrist_sensor_key not in used_sensor_keys:
        return wrist_sensor_key
    for sensor_key in sensor_key_choices_for_kind("realsense"):
        if "/world/scene_" in sensor_key and sensor_key not in used_sensor_keys:
            return sensor_key
    return "/spark/cameras/world/scene_1"


def _heuristic_tactile_sensor_key(used_sensor_keys: set[str], active_arms: list[str]) -> str:
    primary_arm = active_arms[0] if active_arms else "lightning"
    for sensor_key in (
        f"/spark/tactile/{primary_arm}/finger_left",
        f"/spark/tactile/{primary_arm}/finger_right",
    ):
        if sensor_key not in used_sensor_keys:
            return sensor_key
    return f"/spark/tactile/{primary_arm}/finger_left"


def discover_session_devices(config: dict[str, Any]) -> list[dict[str, Any]]:
    active_arms = normalize_active_arms(parse_task_list(str(config.get("active_arms", ""))))
    sensors_file = str(config.get("sensors_file", "")).strip()
    sensor_overrides = load_optional_sensor_overrides(sensors_file) if sensors_file and Path(sensors_file).exists() else {}
    current_selections = _current_selection_map(config)

    devices: list[dict[str, Any]] = []
    used_sensor_keys: set[str] = set()

    realsense_cameras = _discover_realsense_sdk() or _discover_realsense_v4l()
    for camera in realsense_cameras:
        serial_number = str(camera.get("serial_number", "")).strip()
        selection = current_selections.get(_device_key("realsense", serial_number))
        sensor_name, sensor = _matched_sensor_for_realsense(serial_number, sensor_overrides)
        sensor_key = _sensor_key_from_selection_or_sensor(selection=selection, sensor_name=sensor_name, sensor=sensor)
        if not sensor_key:
            sensor_key = _heuristic_camera_sensor_key(str(camera.get("model", "")), used_sensor_keys, active_arms)
        used_sensor_keys.add(sensor_key)
        enabled = selection["enabled"] if selection is not None else _default_enabled(sensor)
        devices.append(
            _device_entry(
                kind="realsense",
                model=str(camera.get("model", "")).strip() or "Intel RealSense",
                serial_number=serial_number,
                sensor_key=sensor_key,
                enabled=enabled,
                sensor=sensor,
            )
        )

    for tactile in _discover_gelsight_v4l(sensor_overrides):
        device_path = str(tactile.get("device_path", "")).strip()
        serial_number = str(tactile.get("serial_number", "")).strip()
        selection = current_selections.get(_device_key("gelsight", device_path))
        sensor_name, sensor = _matched_sensor_for_gelsight(device_path, serial_number, sensor_overrides)
        sensor_key = _sensor_key_from_selection_or_sensor(selection=selection, sensor_name=sensor_name, sensor=sensor)
        if not sensor_key:
            sensor_key = _heuristic_tactile_sensor_key(used_sensor_keys, active_arms)
        used_sensor_keys.add(sensor_key)
        enabled = selection["enabled"] if selection is not None else _default_enabled(sensor)
        devices.append(
            _device_entry(
                kind="gelsight",
                model=str(tactile.get("model", "")).strip() or "GelSight Mini",
                device_path=device_path,
                serial_number=serial_number,
                sensor_key=sensor_key,
                enabled=enabled,
                sensor=sensor,
            )
        )

    return devices
