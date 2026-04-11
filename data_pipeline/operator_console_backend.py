#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import http.client
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import (
    camera_path_parts_for_sensor_key,
    get_git_commit,
    load_yaml,
    make_episode_id,
    tactile_path_parts_for_sensor_key,
)
from data_pipeline.device_discovery import (
    discover_session_devices as discover_runtime_session_devices,
)
from data_pipeline.session_capture_plan import build_session_capture_plan


ROS_SETUP = "/opt/ros/jazzy/setup.bash"
TELEOP_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
CONVERTER_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
SYSTEM_PYTHON = "/usr/bin/python3"
PRESETS_EXAMPLE_PATH = REPO_ROOT / "data_pipeline" / "configs" / "operator_console_presets.example.yaml"
SENSORS_EXAMPLE_PATH = REPO_ROOT / "data_pipeline" / "configs" / "sensors.example.yaml"
STATE_DIR = REPO_ROOT / ".operator_console"
CAPTURE_PLAN_DIR = STATE_DIR / "capture_plans"
SETTINGS_PATH = STATE_DIR / "settings.yaml"
TOPIC_PROBE_SCRIPT = REPO_ROOT / "data_pipeline" / "ros_topic_probe.py"
DATASET_SERVER_PY = REPO_ROOT / "data_pipeline" / "local_dataset_server.py"
VIEWER_REPO = WORKSPACE_ROOT / "lerobot-dataset-visualizer"
VIEWER_BUN = Path.home() / ".bun" / "bin" / "bun"
VIEWER_BUILD_ID = VIEWER_REPO / ".next" / "BUILD_ID"


@dataclass
class ManagedProcess:
    name: str
    display_name: str
    command: str = ""
    process: subprocess.Popen[str] | None = None
    started_at: float | None = None
    state: str = "stopped"
    exit_code: int | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    log_lock: threading.Lock = field(default_factory=threading.Lock)

    def append_log(self, line: str) -> None:
        with self.log_lock:
            self.logs.append(line.rstrip())

    def get_logs(self) -> list[str]:
        with self.log_lock:
            return list(self.logs)


class OperatorConsoleBackend:
    def __init__(self, presets_example_path: Path = PRESETS_EXAMPLE_PATH):
        self.presets_example_path = Path(presets_example_path)
        self.example_form_config = self._load_preset_form_config(self.presets_example_path)
        self.local_settings = self._load_local_settings()
        self.processes = {
            "spark_devices": ManagedProcess("spark_devices", "SPARK Devices"),
            "teleop_gui": ManagedProcess("teleop_gui", "Teleop GUI"),
            "realsense_contract": ManagedProcess("realsense_contract", "RealSense"),
            "gelsight_contract": ManagedProcess("gelsight_contract", "GelSight"),
            "recorder": ManagedProcess("recorder", "Recorder"),
            "converter": ManagedProcess("converter", "Converter"),
            "dataset_server": ManagedProcess("dataset_server", "Dataset Server"),
            "viewer_server": ManagedProcess("viewer_server", "Viewer Server"),
        }
        self.process_lock = threading.Lock()
        self.last_health: dict[str, dict[str, Any]] = {}
        self.health_refresh_in_flight = False
        self.last_action_error = ""
        self.latest_episode_id: str | None = None
        self.latest_dataset_id: str | None = None
        self.latest_viewer_url: str | None = None
        self.latest_conversion_output = ""
        self.latest_episode_notes_output = ""
        self.latest_recording_ok: bool | None = None
        self.latest_recording_check_output = ""
        self.recording_check_running = False
        self.latest_recording_config: dict[str, Any] | None = None
        self.pending_conversion_dataset_id: str | None = None
        self.current_session_capture_plan: dict[str, Any] | None = None
        self.current_session_capture_plan_path: Path | None = None
        self.topic_probe_cache: dict[str, tuple[float, bool]] = {}
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_events: list[dict[str, Any]] = []
        self.session_log_dir = STATE_DIR / "sessions"
        self.session_log_dir.mkdir(parents=True, exist_ok=True)
        CAPTURE_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        self.session_log_path = self.session_log_dir / f"session-{self.session_id}.json"
        self._persist_session_log()

    STARTUP_GRACE_S = {
        "spark_devices": 10.0,
        "teleop_gui": 12.0,
        "realsense_contract": 18.0,
        "gelsight_contract": 12.0,
    }
    STOP_GRACE_S = 5.0

    def _stored_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return str(path.resolve())

    def _resolve_user_path(self, path_ref: str | Path) -> Path:
        candidate = Path(str(path_ref).strip()).expanduser()
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        return candidate

    def _load_preset_spec(self, path: str | Path) -> dict[str, Any]:
        data = load_yaml(path)
        presets = data.get("presets", {})
        if not isinstance(presets, dict) or not presets:
            raise ValueError("Operator preset file must contain a 'presets' mapping")
        if "default" in presets and isinstance(presets["default"], dict):
            spec = presets["default"]
        else:
            first_key = next(iter(presets))
            spec = presets[first_key]
        return json.loads(json.dumps(spec))

    def _merge_with_form_defaults(self, config_like: dict[str, Any]) -> dict[str, Any]:
        base = getattr(self, "example_form_config", {})
        config = json.loads(json.dumps(base))
        for key in (
            "task_name",
            "language_instruction",
            "operator",
            "active_arms",
            "conversion_profile",
        ):
            if key in config_like:
                config[key] = config_like[key]
        session_devices = config_like.get("session_devices", [])
        if isinstance(session_devices, list):
            config["session_devices"] = json.loads(json.dumps(session_devices))
        return config

    def _load_preset_form_config(self, path: str | Path) -> dict[str, Any]:
        spec = self._load_preset_spec(path)
        return self._merge_with_form_defaults(spec)

    def _load_local_settings(self) -> dict[str, Any]:
        if not SETTINGS_PATH.exists():
            return {}
        data = load_yaml(SETTINGS_PATH)
        return data if isinstance(data, dict) else {}

    def _save_local_settings(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.local_settings, handle, sort_keys=True)

    def default_presets_file_path(self) -> Path:
        stored = str(self.local_settings.get("default_presets_file", "")).strip()
        if stored:
            candidate = self._resolve_user_path(stored)
            if candidate.exists():
                return candidate
        return self.presets_example_path

    def default_sensors_file_path(self) -> Path:
        stored = str(self.local_settings.get("default_sensors_file", "")).strip()
        if stored:
            candidate = self._resolve_user_path(stored)
            if candidate.exists():
                return candidate
        return SENSORS_EXAMPLE_PATH

    def get_default_presets_file(self) -> str:
        return self._stored_path(self.default_presets_file_path())

    def get_default_sensors_file(self) -> str:
        return self._stored_path(self.default_sensors_file_path())

    def set_default_presets_file(self, path_ref: str | Path) -> str:
        path = self._resolve_user_path(path_ref)
        if not path.exists():
            raise FileNotFoundError(f"Preset file not found: {path}")
        stored = self._stored_path(path)
        self.local_settings["default_presets_file"] = stored
        self._save_local_settings()
        return stored

    def set_default_sensors_file(self, path_ref: str | Path) -> str:
        path = self._resolve_user_path(path_ref)
        if not path.exists():
            raise FileNotFoundError(f"Sensors file not found: {path}")
        stored = self._stored_path(path)
        self.local_settings["default_sensors_file"] = stored
        self._save_local_settings()
        return stored

    def load_preset_file(self, path_ref: str | Path) -> dict[str, Any]:
        path = self._resolve_user_path(path_ref)
        if not path.exists():
            raise FileNotFoundError(f"Preset file not found: {path}")
        config = self._load_preset_form_config(path)
        self.set_default_presets_file(path)
        return config

    def save_preset_file(self, path_ref: str | Path, config: dict[str, Any]) -> Path:
        path = self._resolve_user_path(path_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"presets": {"default": self._form_config_to_preset(config)}}
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=True)
        self.set_default_presets_file(path)
        return path

    def save_sensors_file(self, path_ref: str | Path, session_devices: list[dict[str, Any]]) -> Path:
        path = self._resolve_user_path(path_ref)
        sensors: dict[str, dict[str, Any]] = {}
        for device in session_devices:
            if not isinstance(device, dict):
                continue
            sensor_key = str(device.get("sensor_key", "")).strip()
            if not sensor_key:
                continue
            if sensor_key in sensors:
                raise ValueError(f"Duplicate sensor assignment for {sensor_key}")
            serial_number = str(device.get("serial_number", "")).strip()
            device_path = str(device.get("device_path", "")).strip()
            entry: dict[str, Any] = {}
            if serial_number:
                entry["serial_number"] = serial_number
            if device_path:
                entry["device_path"] = device_path
            if not entry:
                continue
            sensors[sensor_key] = entry
        if not sensors:
            raise ValueError("No sensor mappings are assigned. Discover devices and assign sensor keys first.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump({"sensors": sensors}, handle, sort_keys=True)
        self.set_default_sensors_file(path)
        return path

    def default_form_config(self, presets_path: str | Path | None = None) -> dict[str, Any]:
        if presets_path is None:
            return self._load_preset_form_config(self.default_presets_file_path())
        return self._load_preset_form_config(presets_path)

    def _form_config_to_preset(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_name": str(config.get("task_name", "")).strip(),
            "language_instruction": str(config.get("language_instruction", "")).strip(),
            "operator": str(config.get("operator", "")).strip(),
            "active_arms": str(config.get("active_arms", "")).strip(),
            "conversion_profile": str(config.get("conversion_profile", "")).strip(),
            "session_devices": json.loads(json.dumps(config.get("session_devices", []))),
        }

    def _published_root(self) -> Path:
        return (REPO_ROOT / "published").resolve()

    def _normalize_published_dataset_target(self, target_ref: str) -> Path:
        published_root = self._published_root()
        ref = str(target_ref).strip()
        if not ref:
            raise ValueError("Published dataset target is empty.")
        candidate = Path(ref).expanduser()
        if candidate.is_absolute():
            target_path = candidate.resolve()
        elif len(candidate.parts) == 1:
            target_path = (published_root / candidate).resolve()
        else:
            target_path = (REPO_ROOT / candidate).resolve()
        try:
            relative = target_path.relative_to(published_root)
        except ValueError as exc:
            raise ValueError(f"Published dataset target must live under {published_root}") from exc
        if len(relative.parts) != 1 or not relative.parts[0]:
            raise ValueError("Published dataset target must be a direct child of published/.")
        return target_path

    def get_published_dataset_target(self) -> str:
        return str(self.local_settings.get("published_dataset_target", "")).strip()

    def set_published_dataset_target(self, target_ref: str) -> str:
        if not str(target_ref).strip():
            self.local_settings.pop("published_dataset_target", None)
            self._save_local_settings()
            return ""
        target_path = self._normalize_published_dataset_target(target_ref)
        stored = str(target_path.relative_to(REPO_ROOT))
        self.local_settings["published_dataset_target"] = stored
        self._save_local_settings()
        return stored

    def _published_dataset_target_path(self, target_ref: str | None = None) -> Path | None:
        ref = str(target_ref or self.get_published_dataset_target()).strip()
        if not ref:
            return None
        return self._normalize_published_dataset_target(ref)

    def session_state(self, config: dict[str, Any]) -> str:
        recorder = self.processes["recorder"]
        converter = self.processes["converter"]
        if recorder.state == "running":
            return "recording"
        if converter.state == "running":
            return "converting"
        if self.latest_viewer_url:
            return "review_ready"
        if self.latest_dataset_id:
            return "converted"
        if self._required_services_healthy(config):
            return "ready_to_record"
        if self._required_service_red(config):
            return "degraded"
        if any(proc.state == "running" for proc in self.processes.values()):
            if any(proc.state == "failed" for proc in self.processes.values()):
                return "degraded"
            return "bringing_up"
        return "idle"

    def snapshot(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_state": self.session_state(config),
            "published_dataset_target": self.get_published_dataset_target(),
            "processes": {
                name: {
                    "display_name": proc.display_name,
                    "state": proc.state,
                    "exit_code": proc.exit_code,
                    "command": proc.command,
                    "started_at": proc.started_at,
                }
                for name, proc in self.processes.items()
            },
            "health": self.last_health,
            "last_action_error": self.last_action_error,
            "latest_episode_id": self.latest_episode_id,
            "latest_dataset_id": self.latest_dataset_id,
            "latest_viewer_url": self.latest_viewer_url,
            "latest_conversion_output": self.latest_conversion_output,
            "latest_episode_notes_output": self.latest_episode_notes_output,
            "latest_recording_ok": self.latest_recording_ok,
            "latest_recording_check_output": self.latest_recording_check_output,
            "recording_check_running": self.recording_check_running,
        }

    def get_process_logs(self, name: str) -> list[str]:
        process = self.processes.get(name)
        if process is None:
            return []
        return process.get_logs()

    def start_named_process(self, name: str, config: dict[str, Any]) -> None:
        if name == "spark_devices":
            self._start_process("spark_devices", self._build_spark_devices_command())
        elif name == "teleop_gui":
            self._start_process("teleop_gui", self._build_teleop_gui_command())
        elif name == "realsense_contract":
            self._start_process("realsense_contract", self._build_realsense_command(config))
        elif name == "gelsight_contract":
            if config.get("gelsight_enabled", False):
                self._start_process("gelsight_contract", self._build_gelsight_command(config))
        elif name == "recorder":
            self.start_recording(config)
            return
        elif name == "converter":
            self.start_conversion(config)
            return
        else:
            raise ValueError(f"Unsupported process name: {name}")
        self._record_event("start_process", {"name": name})

    def stop_named_process(self, name: str) -> None:
        if name == "recorder":
            self.stop_recording()
            return
        if name not in self.processes:
            raise ValueError(f"Unsupported process name: {name}")
        self._stop_process(name)
        self._record_event("stop_process", {"name": name})

    def start_session(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        self.latest_viewer_url = None
        self._start_process("spark_devices", self._build_spark_devices_command())
        self._start_process("teleop_gui", self._build_teleop_gui_command())
        if config.get("realsense_enabled", True):
            self._start_process("realsense_contract", self._build_realsense_command(config))
        if config.get("gelsight_enabled", False):
            self._start_process("gelsight_contract", self._build_gelsight_command(config))
        self._record_event("start_session", {"config": config})

    def stop_session(self) -> None:
        self.stop_recording()
        for name in ("converter", "gelsight_contract", "realsense_contract", "teleop_gui", "spark_devices"):
            self._stop_process(name)
        self.last_action_error = ""
        self.current_session_capture_plan = None
        self.current_session_capture_plan_path = None
        self._record_event("stop_session", {})

    def start_recording(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        if not self._required_services_healthy(config):
            self.last_action_error = "Required services are not healthy enough to record."
            return

        episode_id = make_episode_id()
        self._refresh_session_capture_plan(config)
        self.latest_episode_id = episode_id
        self.latest_episode_notes_output = ""
        self.latest_recording_ok = None
        self.latest_recording_check_output = ""
        self.recording_check_running = False
        self.latest_recording_config = json.loads(json.dumps(config))
        command = self._build_record_command(config, episode_id=episode_id, dry_run=False)
        self._start_process("recorder", command)
        self._record_event("start_recording", {"episode_id": episode_id, "config": config})

    def stop_recording(self) -> None:
        if self.processes["recorder"].state != "running":
            return
        self._stop_process("recorder", sigint=True)
        self._record_event("stop_recording", {"episode_id": self.latest_episode_id})

    def start_conversion(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        if not self.latest_episode_id:
            self.last_action_error = "No recorded episode is known yet."
            return
        target_path = self._published_dataset_target_path()
        if target_path is None:
            self.last_action_error = "Choose a published dataset target before converting."
            return
        command = self._build_convert_command(config, self.latest_episode_id, target_path=target_path)
        self._start_process("converter", command)
        self.pending_conversion_dataset_id = target_path.name
        self.latest_conversion_output = ""
        self._record_event(
            "start_conversion",
            {"episode_id": self.latest_episode_id, "dataset_id": self.pending_conversion_dataset_id},
        )

    def save_latest_episode_notes(self, note_text: str) -> None:
        self.last_action_error = ""
        self.latest_episode_notes_output = ""
        if not self.latest_episode_id:
            self.last_action_error = "No recorded episode is available yet."
            return
        if self.processes["recorder"].state == "running":
            self.last_action_error = "Stop recording before saving episode notes."
            return

        cleaned = note_text.strip()
        if not cleaned:
            self.last_action_error = "Episode notes are empty."
            return

        notes_path = REPO_ROOT / "raw_episodes" / self.latest_episode_id / "notes.md"
        if not notes_path.exists():
            self.last_action_error = f"Notes file not found for {self.latest_episode_id}."
            return

        try:
            existing = notes_path.read_text(encoding="utf-8")
            notes_path.write_text(self._replace_notes_section(existing, cleaned), encoding="utf-8")
        except Exception as exc:
            self.last_action_error = str(exc)
            return

        self.latest_episode_notes_output = f"Saved notes for {self.latest_episode_id}"
        self._record_event("save_episode_notes", {"episode_id": self.latest_episode_id})

    def open_viewer(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        try:
            dataset_id, episode_index, url = self._resolve_viewer_target(config)
            self._ensure_viewer_server(dataset_id)
        except RuntimeError as exc:
            self.last_action_error = str(exc)
            return
        self.latest_dataset_id = dataset_id
        self.latest_viewer_url = url
        if not shutil.which("xdg-open"):
            self.last_action_error = "xdg-open is not available on this system."
            return
        subprocess.Popen(
            ["xdg-open", url],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._record_event("open_viewer", {"url": url})

    def discover_session_devices(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        self.last_action_error = ""
        try:
            return discover_runtime_session_devices(config)
        except Exception as exc:
            self.last_action_error = str(exc)
            return []

    def request_health_refresh(self, config: dict[str, Any]) -> None:
        if self.health_refresh_in_flight:
            return
        self.health_refresh_in_flight = True
        thread = threading.Thread(target=self._refresh_health, args=(config,), daemon=True)
        thread.start()

    def _refresh_health(self, config: dict[str, Any]) -> None:
        try:
            live_topics = self._list_live_topics()
            health = {
                "spark_devices": self._spark_health(config, live_topics),
                "teleop_gui": self._teleop_health(config, live_topics),
                "realsense_contract": self._realsense_health(config, live_topics),
                "gelsight_contract": self._gelsight_health(config, live_topics),
                "recorder": self._recorder_health(),
                "converter": self._converter_health(),
            }
            self.last_health = health
        except Exception as exc:
            self.last_health = {
                "system": {
                    "status": "red",
                    "summary": f"Health refresh failed: {exc}",
                    "details": [],
                }
            }
        finally:
            self.health_refresh_in_flight = False

    def viewer_target_available(self, config: dict[str, Any]) -> bool:
        return self._find_viewer_dataset_id(config) is not None

    def _viewer_dataset_candidates(self, config: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        target_path = self._published_dataset_target_path()
        if target_path is not None:
            candidates.append(target_path.name)
        if self.latest_dataset_id and self.latest_dataset_id not in candidates:
            candidates.append(self.latest_dataset_id)
        return candidates

    def _find_viewer_dataset_id(self, config: dict[str, Any]) -> str | None:
        for dataset_id in self._viewer_dataset_candidates(config):
            info_path = REPO_ROOT / "published" / dataset_id / "meta" / "info.json"
            if info_path.exists():
                return dataset_id
        return None

    def _resolve_viewer_target(self, config: dict[str, Any]) -> tuple[str, int, str]:
        viewer_base_url = self._viewer_base_url()
        dataset_id = self._find_viewer_dataset_id(config)
        if not dataset_id:
            checked = [
                str(REPO_ROOT / "published" / dataset_id / "meta" / "info.json")
                for dataset_id in self._viewer_dataset_candidates(config)
            ]
            raise RuntimeError(
                "Published dataset info not found. Checked: "
                + (", ".join(checked) if checked else "<no dataset id configured>")
            )
        info_path = REPO_ROOT / "published" / dataset_id / "meta" / "info.json"
        with info_path.open("r", encoding="utf-8") as handle:
            info = json.load(handle)
        episode_index = max(int(info.get("total_episodes", 1)) - 1, 0)
        url = f"{viewer_base_url}/local/{dataset_id}/episode_{episode_index}"
        return dataset_id, episode_index, url

    def _build_viewer_server_command(self) -> str:
        if not VIEWER_REPO.exists():
            raise RuntimeError(f"Viewer repo not found: {VIEWER_REPO}")
        if not VIEWER_BUN.exists():
            raise RuntimeError(f"Bun not found: {VIEWER_BUN}")
        if not VIEWER_BUILD_ID.exists():
            raise RuntimeError(
                "Viewer production build is missing. Run ./data_pipeline/setup_viewer_env.sh first."
            )
        dataset_url = f"{self._dataset_base_url()}/datasets"
        return (
            f"cd {shlex.quote(str(VIEWER_REPO))} && "
            "env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY "
            "-u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy "
            f"PORT={shlex.quote(str(self._viewer_port()))} "
            f"DATASET_URL={shlex.quote(dataset_url)} "
            f"{shlex.quote(str(VIEWER_BUN))} start"
        )

    def _build_dataset_server_command(self) -> str:
        return (
            f"{shlex.quote(SYSTEM_PYTHON)} {shlex.quote(str(DATASET_SERVER_PY))} "
            f"--root {shlex.quote(str(self._published_root()))} "
            "--host 127.0.0.1 "
            f"--port {shlex.quote(str(self._dataset_port()))}"
        )

    def _local_base_url(self, env_name: str, default_port: int) -> str:
        override = os.environ.get(env_name, "").strip()
        if override:
            return override.rstrip("/")
        return f"http://127.0.0.1:{default_port}"

    def _default_local_port(self, base: int) -> int:
        uid = os.getuid()
        port = base + uid
        if 1024 <= port <= 65535:
            return port
        return base + (uid % 20000)

    def _viewer_base_url(self) -> str:
        return self._local_base_url("PIPELINE_VIEWER_BASE_URL", self._default_local_port(20000))

    def _dataset_base_url(self) -> str:
        return self._local_base_url("PIPELINE_DATASET_BASE_URL", self._default_local_port(30000))

    def _port_from_base_url(self, url: str) -> int:
        parsed = urllib.parse.urlparse(url)
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme == "http":
            return 80
        if parsed.scheme == "https":
            return 443
        raise RuntimeError(f"URL must include a valid port: {url}")

    def _viewer_port(self) -> int:
        return self._port_from_base_url(self._viewer_base_url())

    def _dataset_port(self) -> int:
        return self._port_from_base_url(self._dataset_base_url())

    def _dataset_info_url(self, dataset_id: str) -> str:
        return f"{self._dataset_base_url()}/datasets/local/{dataset_id}/resolve/main/meta/info.json"

    def _listener_pid(self, port: int, cwd_hint: Path) -> int | None:
        try:
            result = subprocess.run(
                ["ss", "-ltnp", f"( sport = :{port} )"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            return None

        for line in result.stdout.splitlines():
            match = re.search(r"pid=(\d+)", line)
            if not match:
                continue
            pid = int(match.group(1))
            try:
                cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
            except OSError:
                continue
            if cwd.resolve() == cwd_hint.resolve():
                return pid
        return None

    def _stop_existing_listener(self, port: int, cwd_hint: Path) -> None:
        pid = self._listener_pid(port, cwd_hint)
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if self._listener_pid(port, cwd_hint) is None:
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _ensure_managed_http_server(
        self,
        *,
        process_name: str,
        command: str,
        url: str,
        port: int,
        cwd_hint: Path,
        timeout_s: float,
    ) -> None:
        process = self.processes[process_name]
        process_running = process.process is not None and process.process.poll() is None

        if process_running and process.command != command:
            self._stop_process(process_name)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if process.process is None or process.process.poll() is not None:
                    break
                time.sleep(0.1)

        if process.process is not None and process.process.poll() is None and process.command == command:
            if self._url_reachable(url, timeout_s=1.5):
                return

        if self._url_reachable(url, timeout_s=1.5):
            listener_pid = self._listener_pid(port, cwd_hint)
            if listener_pid is not None:
                return
            raise RuntimeError(f"Port {port} is already serving {url} from an unmanaged process.")

        self._stop_existing_listener(port, cwd_hint)
        self._start_process(process_name, command)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._url_reachable(url, timeout_s=1.5):
                return
            time.sleep(0.25)
        raise RuntimeError(f"{self.processes[process_name].display_name} did not become reachable: {url}")

    def _ensure_dataset_server(self) -> None:
        self._ensure_managed_http_server(
            process_name="dataset_server",
            command=self._build_dataset_server_command(),
            url=f"{self._dataset_base_url()}/healthz",
            port=self._dataset_port(),
            cwd_hint=REPO_ROOT,
            timeout_s=10.0,
        )

    def _ensure_viewer_server(self, dataset_id: str) -> None:
        self._ensure_dataset_server()
        dataset_info_url = self._dataset_info_url(dataset_id)
        if not self._url_reachable(dataset_info_url, timeout_s=1.5):
            raise RuntimeError(f"Viewer dataset did not become reachable: {dataset_info_url}")

        self._ensure_managed_http_server(
            process_name="viewer_server",
            command=self._build_viewer_server_command(),
            url=self._viewer_base_url(),
            port=self._viewer_port(),
            cwd_hint=VIEWER_REPO,
            timeout_s=15.0,
        )

    def _url_reachable(self, url: str, timeout_s: float = 2.0) -> bool:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, method="GET")
        try:
            with opener.open(request, timeout=timeout_s) as response:
                return 200 <= int(getattr(response, "status", 200)) < 400
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
            return False

    def _required_services_healthy(self, config: dict[str, Any]) -> bool:
        required = self._required_service_names(config)
        for name in required:
            status = self.last_health.get(name, {}).get("status")
            if status != "green":
                return False
        return True

    def _required_service_red(self, config: dict[str, Any]) -> bool:
        required = self._required_service_names(config)
        for name in required:
            status = self.last_health.get(name, {}).get("status")
            if status == "red":
                return True
        return False

    def _required_service_names(self, config: dict[str, Any]) -> list[str]:
        required = ["spark_devices", "teleop_gui"]
        if config.get("realsense_enabled", True):
            required.append("realsense_contract")
        if config.get("gelsight_enabled", False):
            required.append("gelsight_contract")
        return required

    def _spark_health(self, config: dict[str, Any], live_topics: dict[str, str]) -> dict[str, Any]:
        arms = self._active_arm_list(config)
        required_topics = ["/spark/session/teleop_active"]
        sample_topics = []
        for arm in arms:
            required_topics.append(f"/Spark_angle/{arm}")
            sample_topics.append(f"/Spark_angle/{arm}")
        card = self._build_health_card(
            process_name="spark_devices",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=sample_topics,
        )
        if card["status"] != "green":
            return card

        static_topics = [
            topic
            for topic in sample_topics
            if topic in live_topics
            and not self._float_array_topic_changes_cached(
                topic,
                topic_type=live_topics.get(topic, "std_msgs/msg/Float32MultiArray"),
                timeout_s=1.0,
                min_messages=8,
                min_max_delta=1e-6,
                ttl_s=0.5,
            )
        ]
        if static_topics:
            return {
                "status": "yellow",
                "summary": "SPARK Devices live but static",
                "details": ["No angle change observed on: " + ", ".join(static_topics)],
            }
        return card

    def _teleop_health(self, config: dict[str, Any], live_topics: dict[str, str]) -> dict[str, Any]:
        arms = self._active_arm_list(config)
        required_topics = []
        sample_topics = []
        for arm in arms:
            required_topics.extend(
                [
                    f"/spark/{arm}/robot/joint_state",
                    f"/spark/{arm}/robot/eef_pose",
                    f"/spark/{arm}/robot/tcp_wrench",
                    f"/spark/{arm}/robot/gripper_state",
                    f"/spark/{arm}/teleop/cmd_joint_state",
                    f"/spark/{arm}/teleop/cmd_gripper_state",
                ]
            )
            sample_topics.append(f"/spark/{arm}/robot/joint_state")
        card = self._build_health_card(
            process_name="teleop_gui",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=sample_topics,
        )
        if card["status"] == "yellow":
            card["summary"] = "Teleop running; connect robot in Teleop GUI"
        return card

    def _realsense_health(self, config: dict[str, Any], live_topics: dict[str, str]) -> dict[str, Any]:
        if not config.get("realsense_enabled", True):
            return {"status": "off", "summary": "RealSense disabled", "details": []}
        required_topics = [topic for topic in self._realsense_required_topics(config) if topic.endswith("/color/image_raw")]
        return self._build_health_card(
            process_name="realsense_contract",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=list(required_topics),
        )

    def _gelsight_health(self, config: dict[str, Any], live_topics: dict[str, str]) -> dict[str, Any]:
        if not config.get("gelsight_enabled", False):
            return {"status": "off", "summary": "GelSight disabled", "details": []}
        required_topics = self._gelsight_required_topics(config)
        return self._build_health_card(
            process_name="gelsight_contract",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=list(required_topics),
        )

    def _recorder_health(self) -> dict[str, Any]:
        process = self.processes["recorder"]
        if process.state == "running":
            return {"status": "green", "summary": "Recorder running", "details": []}
        if process.state == "failed":
            return {
                "status": "red",
                "summary": f"Recorder failed with exit code {process.exit_code}",
                "details": [],
            }
        if self.recording_check_running:
            return {
                "status": "yellow",
                "summary": "Analyzing last recording",
                "details": [self.latest_episode_id] if self.latest_episode_id else [],
            }
        if self.latest_episode_id and self.latest_recording_ok is False:
            return {
                "status": "red",
                "summary": "Last recording incomplete",
                "details": self.latest_recording_check_output.splitlines()[:6],
            }
        if self.latest_episode_id and self.latest_recording_ok is True:
            return {
                "status": "yellow",
                "summary": "Last recording complete",
                "details": [self.latest_episode_id],
            }
        return {"status": "off", "summary": "Recorder not running", "details": []}

    def _converter_health(self) -> dict[str, Any]:
        process = self.processes["converter"]
        if process.state == "running":
            return {"status": "green", "summary": "Converter running", "details": [self.latest_episode_id] if self.latest_episode_id else []}
        if process.state == "failed":
            return {
                "status": "red",
                "summary": f"Converter failed with exit code {process.exit_code}",
                "details": process.get_logs()[-4:],
            }
        if self.latest_episode_id and self.latest_recording_ok is True:
            return {
                "status": "yellow",
                "summary": "Latest recording ready to convert",
                "details": [self.latest_episode_id],
            }
        if self.latest_dataset_id:
            return {
                "status": "yellow",
                "summary": "Latest dataset ready for review",
                "details": [self.latest_dataset_id],
            }
        return {"status": "off", "summary": "Converter idle", "details": []}

    def _build_health_card(
        self,
        *,
        process_name: str,
        live_topics: dict[str, str],
        required_topics: list[str],
        sample_topics: list[str],
    ) -> dict[str, Any]:
        process = self.processes[process_name]
        missing_topics = [topic for topic in required_topics if topic not in live_topics]
        dead_sample_topics = [
            topic
            for topic in sample_topics
            if topic in live_topics
            and not self._topic_has_message_cached(topic, topic_type=live_topics.get(topic, ""))
        ]
        details = []
        if missing_topics:
            details.append("Missing topics: " + ", ".join(missing_topics))
        if dead_sample_topics:
            details.append("No messages on: " + ", ".join(dead_sample_topics))
        startup_grace = self.STARTUP_GRACE_S.get(process_name, 0.0)
        within_grace = process.started_at is not None and (time.time() - process.started_at) < startup_grace
        log_hint = self._latest_log_hint(process)
        if log_hint:
            details.append("Last log: " + log_hint)

        if process.state == "failed":
            return {
                "status": "red",
                "summary": f"{process.display_name} failed",
                "details": details or [f"Exit code {process.exit_code}"],
            }
        if missing_topics or dead_sample_topics:
            if process.state == "running" and within_grace:
                return {
                    "status": "yellow",
                    "summary": f"{process.display_name} starting",
                    "details": details,
                }
            if process.state == "running":
                return {
                    "status": "yellow",
                    "summary": f"{process.display_name} running but not ready",
                    "details": details,
                }
            return {
                "status": "red",
                "summary": f"{process.display_name} not ready",
                "details": details,
                }
        if process.state == "running":
            return {
                "status": "green",
                "summary": f"{process.display_name} healthy",
                "details": [],
            }
        return {
            "status": "yellow",
            "summary": f"{process.display_name} topics healthy but process unmanaged",
            "details": [],
        }

    def _latest_log_hint(self, process: ManagedProcess) -> str | None:
        for line in reversed(process.get_logs()):
            text = line.strip()
            if not text or text.startswith("$ "):
                continue
            return text
        return None

    def _active_arm_list(self, config: dict[str, Any]) -> list[str]:
        return [
            item.strip()
            for item in str(config.get("active_arms", "")).split(",")
            if item.strip()
        ]

    def _enabled_session_devices(self, config: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        devices = config.get("session_devices", [])
        if not isinstance(devices, list):
            return []
        return [
            device
            for device in devices
            if isinstance(device, dict)
            and bool(device.get("enabled", False))
            and str(device.get("kind", "")).strip() == kind
        ]

    def _realsense_required_topics(self, config: dict[str, Any]) -> list[str]:
        topics: list[str] = []
        for device in self._enabled_session_devices(config, "realsense"):
            sensor_key = str(device.get("sensor_key", "")).strip()
            parts = camera_path_parts_for_sensor_key(sensor_key)
            if parts is None:
                continue
            attachment, slot = parts
            prefix = f"/spark/cameras/{attachment}/{slot}"
            topics.extend([f"{prefix}/color/image_raw", f"{prefix}/depth/image_rect_raw"])
        return topics

    def _gelsight_required_topics(self, config: dict[str, Any]) -> list[str]:
        topics: list[str] = []
        for device in self._enabled_session_devices(config, "gelsight"):
            sensor_key = str(device.get("sensor_key", "")).strip()
            parts = tactile_path_parts_for_sensor_key(sensor_key)
            if parts is None:
                continue
            arm, finger = parts
            topics.append(f"/spark/tactile/{arm}/{finger}/color/image_raw")
        return topics

    def _list_live_topics(self) -> dict[str, str]:
        result = self._run_ros_command("ros2 topic list -t", timeout=5.0)
        topics: dict[str, str] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "[" not in line or "]" not in line:
                continue
            topic, type_name = line.rsplit("[", maxsplit=1)
            topics[topic.strip()] = type_name.rstrip("]").strip()
        return topics

    def _topic_has_message(self, topic: str, topic_type: str = "", timeout_s: float = 1.0) -> bool:
        probe_command = [
            shlex.quote(SYSTEM_PYTHON),
            shlex.quote(str(TOPIC_PROBE_SCRIPT)),
            "--topic",
            shlex.quote(topic),
            "--timeout",
            shlex.quote(str(timeout_s)),
        ]
        if topic_type:
            probe_command.extend(["--topic-type", shlex.quote(topic_type)])
        try:
            result = self._run_ros_command(
                " ".join(probe_command),
                timeout=max(2.0, timeout_s + 1.0),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def _topic_has_message_cached(
        self,
        topic: str,
        topic_type: str = "",
        timeout_s: float = 0.8,
        ttl_s: float = 5.0,
    ) -> bool:
        cache_key = f"{topic}|{topic_type}"
        cached = self.topic_probe_cache.get(cache_key)
        now = time.time()
        if cached is not None:
            ts, value = cached
            if (now - ts) < ttl_s:
                return value
        value = self._topic_has_message(topic, topic_type=topic_type, timeout_s=timeout_s)
        self.topic_probe_cache[cache_key] = (now, value)
        return value

    def _float_array_topic_changes(
        self,
        topic: str,
        topic_type: str = "std_msgs/msg/Float32MultiArray",
        timeout_s: float = 1.0,
        min_messages: int = 8,
        min_max_delta: float = 1e-6,
    ) -> bool:
        probe_command = [
            shlex.quote(SYSTEM_PYTHON),
            shlex.quote(str(TOPIC_PROBE_SCRIPT)),
            "--topic",
            shlex.quote(topic),
            "--topic-type",
            shlex.quote(topic_type),
            "--timeout",
            shlex.quote(str(timeout_s)),
            "--min-messages",
            shlex.quote(str(min_messages)),
            "--require-float-array-change",
            "--min-max-delta",
            shlex.quote(str(min_max_delta)),
        ]
        try:
            result = self._run_ros_command(
                " ".join(probe_command),
                timeout=max(2.0, timeout_s + 1.0),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def _float_array_topic_changes_cached(
        self,
        topic: str,
        topic_type: str = "std_msgs/msg/Float32MultiArray",
        timeout_s: float = 1.0,
        min_messages: int = 8,
        min_max_delta: float = 1e-6,
        ttl_s: float = 0.5,
    ) -> bool:
        cache_key = f"dynamic|{topic}|{topic_type}|{min_messages}|{min_max_delta}"
        cached = self.topic_probe_cache.get(cache_key)
        now = time.time()
        if cached is not None:
            ts, value = cached
            if (now - ts) < ttl_s:
                return value
        value = self._float_array_topic_changes(
            topic,
            topic_type=topic_type,
            timeout_s=timeout_s,
            min_messages=min_messages,
            min_max_delta=min_max_delta,
        )
        self.topic_probe_cache[cache_key] = (now, value)
        return value

    def _start_process(self, name: str, command: str) -> None:
        with self.process_lock:
            process = self.processes[name]
            if process.process is not None and process.process.poll() is None:
                return
            popen = subprocess.Popen(
                ["/bin/bash", "-lc", command],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            process.process = popen
            process.command = command
            process.started_at = time.time()
            process.state = "running"
            process.exit_code = None
            process.logs.clear()
            process.append_log(f"$ {command}")
            reader = threading.Thread(target=self._drain_logs, args=(name, popen), daemon=True)
            reader.start()

    def _stop_process(self, name: str, sigint: bool = False) -> None:
        with self.process_lock:
            process = self.processes[name]
            if process.process is None or process.process.poll() is not None:
                return
            popen = process.process
            try:
                if sigint:
                    os.killpg(popen.pid, signal.SIGINT)
                else:
                    os.killpg(popen.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.state = "stopping"
        watcher = threading.Thread(
            target=self._escalate_stop_if_needed,
            args=(name, popen),
            daemon=True,
        )
        watcher.start()

    def _escalate_stop_if_needed(self, name: str, popen: subprocess.Popen[str]) -> None:
        try:
            popen.wait(timeout=self.STOP_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            pass

        with self.process_lock:
            process = self.processes[name]
            if process.process is not popen or popen.poll() is not None:
                return
            try:
                os.killpg(popen.pid, signal.SIGKILL)
                process.append_log(
                    f"[operator-console] escalated stop to SIGKILL after {self.STOP_GRACE_S:.1f}s grace"
                )
            except ProcessLookupError:
                return

    def _drain_logs(self, name: str, popen: subprocess.Popen[str]) -> None:
        process = self.processes[name]
        assert popen.stdout is not None
        for line in popen.stdout:
            process.append_log(line)
        exit_code = popen.wait()
        if (
            name == "recorder"
            and exit_code in {0, -signal.SIGINT, -signal.SIGTERM, 130, 143}
            and self.latest_episode_id
            and self.latest_recording_config is not None
        ):
            self.recording_check_running = True
        process.exit_code = exit_code
        if process.state == "stopping" and exit_code in {0, -signal.SIGINT, -signal.SIGTERM, 130, 143}:
            process.state = "stopped"
        elif exit_code == 0:
            process.state = "stopped"
        else:
            process.state = "failed"

        if name == "converter":
            self.latest_conversion_output = "\n".join(process.get_logs()[-40:])
            if exit_code == 0 and self.pending_conversion_dataset_id:
                self.latest_dataset_id = self.pending_conversion_dataset_id
                self._record_event(
                    "conversion_complete",
                    {
                        "dataset_id": self.pending_conversion_dataset_id,
                        "episode_id": self.latest_episode_id,
                    },
                )
            elif exit_code != 0:
                self.last_action_error = "Convert failed."
            self.pending_conversion_dataset_id = None
        elif name == "recorder":
            if exit_code not in {0, -signal.SIGINT, -signal.SIGTERM, 130, 143}:
                self.last_action_error = "Recording failed."
            self._finalize_recording_after_exit(exit_code)

    def _run_ros_command(
        self,
        command: str,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        full = f"source {shlex.quote(ROS_SETUP)} && {command}"
        return subprocess.run(
            ["/bin/bash", "-lc", full],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=check,
        )

    def _build_spark_devices_command(self) -> str:
        return (
            f"source {shlex.quote(ROS_SETUP)} && "
            f"{shlex.quote(str(TELEOP_PYTHON))} TeleopSoftware/launch_devs.py"
        )

    def _build_teleop_gui_command(self) -> str:
        return (
            f"source {shlex.quote(ROS_SETUP)} && "
            f"{shlex.quote(str(TELEOP_PYTHON))} TeleopSoftware/launch.py"
        )

    def _build_realsense_command(self, config: dict[str, Any]) -> str:
        camera_specs: list[str] = []
        for device in self._enabled_session_devices(config, "realsense"):
            sensor_key = str(device.get("sensor_key", "")).strip()
            serial = str(device.get("serial_number", "")).strip()
            parts = camera_path_parts_for_sensor_key(sensor_key)
            if parts is None or not serial:
                continue
            attachment, slot = parts
            camera_specs.append(f"{attachment};{slot};{serial};640,480,30;640,480,30")
        if not camera_specs:
            raise RuntimeError("No enabled RealSense session devices are configured.")
        return (
            f"source {shlex.quote(ROS_SETUP)} && "
            f"ros2 launch data_pipeline/launch/realsense_contract.launch.py "
            f"camera_specs:={shlex.quote('|'.join(camera_specs))}"
        )

    def _build_gelsight_command(self, config: dict[str, Any]) -> str:
        sensor_specs: list[str] = []
        for device in self._enabled_session_devices(config, "gelsight"):
            sensor_key = str(device.get("sensor_key", "")).strip()
            device_path = str(device.get("device_path", "")).strip()
            parts = tactile_path_parts_for_sensor_key(sensor_key)
            if parts is None or not device_path:
                continue
            arm, finger = parts
            sensor_specs.append(f"{arm};{finger};{device_path}")
        if not sensor_specs:
            raise RuntimeError("No enabled GelSight session devices are configured.")
        parts = [
            f"source {shlex.quote(ROS_SETUP)}",
            "ros2 launch data_pipeline/launch/gelsight_contract.launch.py",
            f"sensor_specs:={shlex.quote('|'.join(sensor_specs))}",
        ]
        return " && ".join(parts[:1]) + " && " + " ".join(parts[1:])

    def _build_record_command(self, config: dict[str, Any], *, episode_id: str, dry_run: bool) -> str:
        args = [
            shlex.quote(SYSTEM_PYTHON),
            "data_pipeline/record_episode.py",
            "--task-name",
            shlex.quote(str(config["task_name"])),
            "--language-instruction",
            shlex.quote(str(config.get("language_instruction", ""))),
            "--operator",
            shlex.quote(str(config["operator"])),
            "--active-arms",
            shlex.quote(str(config["active_arms"])),
            "--sensors-file",
            shlex.quote(str(config["sensors_file"])),
        ]
        if episode_id:
            args.extend(["--episode-id", shlex.quote(episode_id)])
        if self.current_session_capture_plan_path is not None:
            args.extend(["--session-plan-file", shlex.quote(str(self.current_session_capture_plan_path))])
        if dry_run:
            args.append("--dry-run")
        return f"source {shlex.quote(ROS_SETUP)} && " + " ".join(args)

    def _build_convert_command(self, config: dict[str, Any], episode_id: str, *, target_path: Path) -> str:
        episode_dir = REPO_ROOT / "raw_episodes" / episode_id
        published_root = target_path.parent
        dataset_id = target_path.name
        profile_ref = str(config.get("conversion_profile", "")).strip()
        if not profile_ref:
            raise RuntimeError("Choose a conversion profile before converting.")
        profile_path = self._resolve_user_path(profile_ref)
        if not profile_path.is_file():
            raise FileNotFoundError(f"Conversion profile not found: {profile_path}")
        args = [
            shlex.quote(str(CONVERTER_PYTHON)),
            "data_pipeline/convert_episode_bag_to_lerobot.py",
            shlex.quote(str(episode_dir)),
            "--published-dataset-id",
            shlex.quote(dataset_id),
        ]
        args.extend(["--published-root", shlex.quote(str(published_root))])
        args.extend(["--profile", shlex.quote(str(profile_path))])
        return f"source {shlex.quote(ROS_SETUP)} && " + " ".join(args)

    def _required_record_topics(self, config: dict[str, Any]) -> list[str]:
        topics: list[str] = ["/spark/session/teleop_active"]
        for arm in self._active_arm_list(config):
            topics.extend(
                [
                    f"/spark/{arm}/robot/joint_state",
                    f"/spark/{arm}/robot/eef_pose",
                    f"/spark/{arm}/robot/tcp_wrench",
                    f"/spark/{arm}/robot/gripper_state",
                    f"/spark/{arm}/teleop/cmd_joint_state",
                    f"/spark/{arm}/teleop/cmd_gripper_state",
                ]
            )
        if config.get("realsense_enabled", True):
            topics.extend(self._realsense_required_topics(config))
        if config.get("gelsight_enabled", False):
            topics.extend(self._gelsight_required_topics(config))
        return topics

    def _finalize_recording_after_exit(self, exit_code: int) -> None:
        success_codes = {0, -signal.SIGINT, -signal.SIGTERM, 130, 143}
        if exit_code not in success_codes or not self.latest_episode_id or self.latest_recording_config is None:
            return
        try:
            ok, output = self._analyze_recording(self.latest_episode_id, self.latest_recording_config)
            self.latest_recording_ok = ok
            self.latest_recording_check_output = output
            if not ok:
                self.last_action_error = "Recording integrity check failed."
            self._record_event(
                "recording_check",
                {
                    "episode_id": self.latest_episode_id,
                    "ok": ok,
                    "output": output,
                },
            )
        finally:
            self.recording_check_running = False

    def _analyze_recording(self, episode_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        metadata_path = REPO_ROOT / "raw_episodes" / episode_id / "bag" / "metadata.yaml"
        if not metadata_path.exists():
            return False, f"Recording metadata not found: {metadata_path}"

        metadata = load_yaml(metadata_path)
        bag_info = metadata.get("rosbag2_bagfile_information", {})
        counts: dict[str, int] = {}
        for entry in bag_info.get("topics_with_message_count", []):
            topic_metadata = entry.get("topic_metadata", {})
            topic_name = topic_metadata.get("name")
            if topic_name:
                counts[str(topic_name)] = int(entry.get("message_count", 0))

        required_topics = self._required_record_topics(config)
        zero_topics = [topic for topic in required_topics if counts.get(topic, 0) <= 0]
        duration_ns = int(bag_info.get("duration", {}).get("nanoseconds", 0))
        duration_s = duration_ns / 1_000_000_000 if duration_ns else 0.0
        lines = [
            f"episode_id={episode_id}",
            f"duration_s={duration_s:.3f}",
            f"message_count={int(bag_info.get('message_count', 0))}",
        ]
        if zero_topics:
            lines.append("Zero-message required topics:")
            lines.extend(zero_topics)
            return False, "\n".join(lines)
        lines.append("Required topics all have messages.")
        return True, "\n".join(lines)

    def _config_signature(self, config: dict[str, Any]) -> str:
        keys = [
            "task_name",
            "language_instruction",
            "operator",
            "active_arms",
            "sensors_file",
            "gelsight_enabled",
            "session_devices",
        ]
        payload = {key: config.get(key) for key in keys}
        return json.dumps(payload, sort_keys=True)

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            "payload": payload,
        }
        self.session_events.append(event)
        self._persist_session_log()

    def _persist_session_log(self) -> None:
        payload = {
            "session_id": self.session_id,
            "git_commit": get_git_commit(),
            "events": self.session_events,
            "latest_episode_id": self.latest_episode_id,
            "latest_dataset_id": self.latest_dataset_id,
            "latest_viewer_url": self.latest_viewer_url,
            "latest_recording_ok": self.latest_recording_ok,
            "current_session_capture_plan": self.current_session_capture_plan,
        }
        with self.session_log_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _refresh_session_capture_plan(self, config: dict[str, Any]) -> None:
        plan = build_session_capture_plan(config, session_id=self.session_id)
        plan_path = CAPTURE_PLAN_DIR / f"session-{self.session_id}.json"
        with plan_path.open("w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=2, sort_keys=True)
            handle.write("\n")
        self.current_session_capture_plan = plan
        self.current_session_capture_plan_path = plan_path
        self._persist_session_log()

    @staticmethod
    def _replace_notes_section(existing_text: str, note_text: str) -> str:
        lines = existing_text.splitlines()
        try:
            notes_index = lines.index("## Notes")
        except ValueError:
            prefix = lines[:]
            if prefix and prefix[-1] != "":
                prefix.append("")
            prefix.extend(["## Notes", ""])
            return "\n".join(prefix + note_text.splitlines()) + "\n"

        updated = lines[: notes_index + 1] + [""] + note_text.splitlines()
        return "\n".join(updated) + "\n"
