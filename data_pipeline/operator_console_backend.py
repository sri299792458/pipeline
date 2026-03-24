#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import get_git_commit, load_yaml, make_episode_id
from data_pipeline.device_discovery import discover_session_devices as discover_runtime_session_devices
from data_pipeline.session_capture_plan import build_session_capture_plan


ROS_SETUP = "/opt/ros/jazzy/setup.bash"
TELEOP_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
CONVERTER_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
SYSTEM_PYTHON = "/usr/bin/python3"
PRESETS_PATH = REPO_ROOT / "data_pipeline" / "configs" / "operator_console_presets.yaml"
STATE_DIR = REPO_ROOT / ".operator_console"
CAPTURE_PLAN_DIR = STATE_DIR / "capture_plans"
TOPIC_PROBE_SCRIPT = REPO_ROOT / "data_pipeline" / "ros_topic_probe.py"
VIEWER_REPO = REPO_ROOT / "lerobot-dataset-visualizer"
VIEWER_BUN = Path.home() / ".bun" / "bin" / "bun"


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
    def __init__(self, presets_path: Path = PRESETS_PATH):
        self.presets_path = Path(presets_path)
        self.presets = self._load_presets()
        self.processes = {
            "spark_devices": ManagedProcess("spark_devices", "SPARK Devices"),
            "teleop_gui": ManagedProcess("teleop_gui", "Teleop GUI"),
            "realsense_contract": ManagedProcess("realsense_contract", "RealSense"),
            "gelsight_contract": ManagedProcess("gelsight_contract", "GelSight"),
            "recorder": ManagedProcess("recorder", "Recorder"),
            "converter": ManagedProcess("converter", "Converter"),
            "viewer_server": ManagedProcess("viewer_server", "Viewer Server"),
        }
        self.process_lock = threading.Lock()
        self.last_health: dict[str, dict[str, Any]] = {}
        self.health_refresh_in_flight = False
        self.validation_running = False
        self.last_validation_ok = False
        self.last_validation_output = ""
        self.last_validation_signature = ""
        self.last_action_error = ""
        self.latest_episode_id: str | None = None
        self.latest_dataset_id: str | None = None
        self.latest_viewer_url: str | None = None
        self.latest_conversion_output = ""
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

    def _load_presets(self) -> dict[str, dict[str, Any]]:
        data = load_yaml(self.presets_path)
        presets = data.get("presets", {})
        if not isinstance(presets, dict):
            raise ValueError("operator_console_presets.yaml must contain a 'presets' mapping")
        return presets

    def list_presets(self) -> list[tuple[str, str]]:
        return [
            (preset_id, str(spec.get("label", preset_id)))
            for preset_id, spec in self.presets.items()
        ]

    def get_preset(self, preset_id: str) -> dict[str, Any]:
        spec = self.presets[preset_id]
        return json.loads(json.dumps(spec))

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
        if self.last_validation_ok and self._config_signature(config) == self.last_validation_signature:
            return "ready_to_record"
        if self._required_services_healthy(config):
            return "ready_for_dry_run"
        if self._required_service_red(config):
            return "degraded"
        if any(proc.state == "running" for proc in self.processes.values()):
            if any(proc.state == "failed" for proc in self.processes.values()):
                return "degraded"
            return "bringing_up"
        return "idle"

    def snapshot(self, config: dict[str, Any]) -> dict[str, Any]:
        preview_capture_plan, preview_capture_plan_error = self._preview_session_capture_plan(config)
        return {
            "session_state": self.session_state(config),
            "validation_state": self.validation_state(config),
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
            "last_validation_ok": self.last_validation_ok,
            "last_validation_output": self.last_validation_output,
            "last_action_error": self.last_action_error,
            "latest_episode_id": self.latest_episode_id,
            "latest_dataset_id": self.latest_dataset_id,
            "latest_viewer_url": self.latest_viewer_url,
            "latest_conversion_output": self.latest_conversion_output,
            "latest_recording_ok": self.latest_recording_ok,
            "latest_recording_check_output": self.latest_recording_check_output,
            "recording_check_running": self.recording_check_running,
            "current_session_capture_plan": self.current_session_capture_plan,
            "preview_session_capture_plan": preview_capture_plan,
            "preview_session_capture_plan_error": preview_capture_plan_error,
        }

    def validation_state(self, config: dict[str, Any]) -> str:
        if self.validation_running:
            return "running"
        if self.last_validation_ok and self.last_validation_signature == self._config_signature(config):
            return "passed"
        if self.last_validation_output and not self.last_validation_ok:
            return "failed"
        if self.last_validation_ok and self.last_validation_signature != self._config_signature(config):
            return "stale"
        return "not_run"

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
        self._refresh_session_capture_plan(config)
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
        self.validation_running = False
        self.last_validation_ok = False
        self.last_validation_signature = ""
        self.last_validation_output = ""
        self.last_action_error = ""
        self.current_session_capture_plan = None
        self.current_session_capture_plan_path = None
        self._record_event("stop_session", {})

    def start_validation(self, config: dict[str, Any]) -> None:
        if self.validation_running:
            return
        thread = threading.Thread(target=self._run_validation, args=(config,), daemon=True)
        thread.start()

    def start_recording(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        if not self._required_services_healthy(config):
            self.last_action_error = "Required services are not healthy enough to record."
            return
        if not self.last_validation_ok or self.last_validation_signature != self._config_signature(config):
            self.last_action_error = "Run Validate successfully for the current configuration before recording."
            return

        episode_id = make_episode_id()
        self._refresh_session_capture_plan(config)
        self.latest_episode_id = episode_id
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
        command = self._build_convert_command(config, self.latest_episode_id)
        self._start_process("converter", command)
        self.pending_conversion_dataset_id = str(config["dataset_id"])
        self.latest_conversion_output = ""
        self._record_event(
            "start_conversion",
            {"episode_id": self.latest_episode_id, "dataset_id": self.pending_conversion_dataset_id},
        )

    def open_viewer(self, config: dict[str, Any]) -> None:
        self.last_action_error = ""
        try:
            dataset_id, episode_index, url = self._resolve_viewer_target(config)
            self._ensure_viewer_server(config, dataset_id, episode_index)
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
        config_dataset_id = str(config.get("dataset_id", "")).strip()
        if config_dataset_id:
            candidates.append(config_dataset_id)
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
        viewer_base_url = str(config.get("viewer_base_url", "")).strip().rstrip("/")
        if not viewer_base_url:
            raise RuntimeError("Viewer base URL is empty.")
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

    def _build_viewer_server_command(self, config: dict[str, Any], dataset_id: str, episode_index: int) -> str:
        if not VIEWER_REPO.exists():
            raise RuntimeError(f"Viewer repo not found: {VIEWER_REPO}")
        if not VIEWER_BUN.exists():
            raise RuntimeError(f"Bun not found: {VIEWER_BUN}")
        viewer_base_url = str(config.get("viewer_base_url", "")).strip().rstrip("/")
        dataset_url = f"{viewer_base_url}/datasets"
        localhost_dataset_url = "http://localhost:3000/datasets"
        return (
            f"cd {shlex.quote(str(VIEWER_REPO))} && "
            "env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY "
            "-u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy "
            f"NEXT_PUBLIC_DATASET_URL={shlex.quote(dataset_url)} "
            f"DATASET_URL={shlex.quote(localhost_dataset_url)} "
            f"REPO_ID={shlex.quote(f'local/{dataset_id}')} "
            f"EPISODES={shlex.quote(str(episode_index))} "
            f"{shlex.quote(str(VIEWER_BUN))} start"
        )

    def _ensure_viewer_server(self, config: dict[str, Any], dataset_id: str, episode_index: int) -> None:
        viewer_base_url = str(config.get("viewer_base_url", "")).strip().rstrip("/")
        command = self._build_viewer_server_command(config, dataset_id, episode_index)
        process = self.processes["viewer_server"]
        process_running = process.process is not None and process.process.poll() is None

        if process_running and process.command != command:
            self._stop_process("viewer_server")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if process.process is None or process.process.poll() is not None:
                    break
                time.sleep(0.1)

        if process.process is not None and process.process.poll() is None and process.command == command:
            if self._url_reachable(viewer_base_url, timeout_s=1.5):
                return

        if self._url_reachable(viewer_base_url, timeout_s=1.5):
            return

        self._start_process("viewer_server", command)
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self._url_reachable(viewer_base_url, timeout_s=1.5):
                return
            time.sleep(0.25)
        raise RuntimeError(f"Viewer server did not become reachable: {viewer_base_url}")

    def _url_reachable(self, url: str, timeout_s: float = 2.0) -> bool:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, method="GET")
        try:
            with opener.open(request, timeout=timeout_s) as response:
                return 200 <= int(getattr(response, "status", 200)) < 400
        except (urllib.error.URLError, TimeoutError, ValueError):
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
        required_topics = []
        sample_topics = []
        for arm in arms:
            required_topics.extend([f"/Spark_angle/{arm}", f"/Spark_enable/{arm}"])
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
        required_topics = [
            "/spark/cameras/wrist/color/image_raw",
            "/spark/cameras/scene/color/image_raw",
        ]
        return self._build_health_card(
            process_name="realsense_contract",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=list(required_topics),
        )

    def _gelsight_health(self, config: dict[str, Any], live_topics: dict[str, str]) -> dict[str, Any]:
        if not config.get("gelsight_enabled", False):
            return {"status": "off", "summary": "GelSight disabled", "details": []}
        required_topics = []
        if config.get("gelsight_enable_left", False):
            required_topics.append("/spark/tactile/left/color/image_raw")
        if config.get("gelsight_enable_right", False):
            required_topics.append("/spark/tactile/right/color/image_raw")
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

    def _run_validation(self, config: dict[str, Any]) -> None:
        self.validation_running = True
        self.last_validation_ok = False
        self.last_validation_signature = ""
        probe_errors = self._probe_required_streams(config)
        if probe_errors:
            self.last_validation_output = "\n".join(probe_errors)
            self.last_action_error = "Validate failed."
            self._record_event(
                "validate",
                {
                    "ok": False,
                    "returncode": None,
                    "output": self.last_validation_output,
                },
            )
            self.validation_running = False
            return

        command = self._build_record_command(config, episode_id="", dry_run=True)
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=15.0,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            self.last_validation_output = output.strip()
            self.last_validation_ok = result.returncode == 0
            self.last_validation_signature = self._config_signature(config) if self.last_validation_ok else ""
            self.last_action_error = "" if self.last_validation_ok else "Validate failed."
            self._record_event(
                "validate",
                {
                    "ok": self.last_validation_ok,
                    "returncode": result.returncode,
                    "output": self.last_validation_output,
                },
            )
        except Exception as exc:
            self.last_validation_ok = False
            self.last_validation_signature = ""
            self.last_validation_output = str(exc)
            self.last_action_error = f"Validate failed: {exc}"
        finally:
            self.validation_running = False

    def _probe_required_streams(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        active_arms = self._active_arm_list(config)
        if active_arms:
            spark_topic = f"/Spark_angle/{active_arms[0]}"
            if not self._topic_has_message(spark_topic, topic_type="std_msgs/msg/Float32MultiArray", timeout_s=2.5):
                errors.append(f"Timed out waiting for Spark stream: {spark_topic}")
            robot_topic = f"/spark/{active_arms[0]}/robot/joint_state"
            if not self._topic_has_message(robot_topic, topic_type="sensor_msgs/msg/JointState", timeout_s=2.5):
                errors.append(f"Timed out waiting for robot state: {robot_topic}")
        if config.get("realsense_enabled", True):
            for topic in [
                "/spark/cameras/wrist/color/image_raw",
                "/spark/cameras/scene/color/image_raw",
            ]:
                if not self._topic_has_message(topic, topic_type="sensor_msgs/msg/Image", timeout_s=2.5):
                    errors.append(f"Timed out waiting for camera stream: {topic}")
        if config.get("gelsight_enabled", False):
            if config.get("gelsight_enable_left", False):
                topic = "/spark/tactile/left/color/image_raw"
                if not self._topic_has_message(topic, topic_type="sensor_msgs/msg/Image", timeout_s=2.5):
                    errors.append(f"Timed out waiting for tactile stream: {topic}")
            if config.get("gelsight_enable_right", False):
                topic = "/spark/tactile/right/color/image_raw"
                if not self._topic_has_message(topic, topic_type="sensor_msgs/msg/Image", timeout_s=2.5):
                    errors.append(f"Timed out waiting for tactile stream: {topic}")
        return errors

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
        wrist = shlex.quote(str(config.get("wrist_serial_no", "")).strip())
        scene = shlex.quote(str(config.get("scene_serial_no", "")).strip())
        return (
            f"source {shlex.quote(ROS_SETUP)} && "
            f"ros2 launch data_pipeline/launch/realsense_contract.launch.py "
            f"wrist_serial_no:={wrist} scene_serial_no:={scene}"
        )

    def _build_gelsight_command(self, config: dict[str, Any]) -> str:
        parts = [
            f"source {shlex.quote(ROS_SETUP)}",
            "ros2 launch data_pipeline/launch/gelsight_contract.launch.py",
            f"enable_left:={'true' if config.get('gelsight_enable_left', False) else 'false'}",
            f"enable_right:={'true' if config.get('gelsight_enable_right', False) else 'false'}",
        ]
        left_path = str(config.get("gelsight_left_device_path", "")).strip()
        right_path = str(config.get("gelsight_right_device_path", "")).strip()
        if left_path:
            parts.append(f"left_device_path:={shlex.quote(left_path)}")
        if right_path:
            parts.append(f"right_device_path:={shlex.quote(right_path)}")
        return " && ".join(parts[:1]) + " && " + " ".join(parts[1:])

    def _build_record_command(self, config: dict[str, Any], *, episode_id: str, dry_run: bool) -> str:
        args = [
            shlex.quote(SYSTEM_PYTHON),
            "data_pipeline/record_episode.py",
            "--dataset-id",
            shlex.quote(str(config["dataset_id"])),
            "--task-name",
            shlex.quote(str(config["task_name"])),
            "--language-instruction",
            shlex.quote(str(config.get("language_instruction", ""))),
            "--robot-id",
            shlex.quote(str(config["robot_id"])),
            "--operator",
            shlex.quote(str(config["operator"])),
            "--active-arms",
            shlex.quote(str(config["active_arms"])),
            "--sensors-file",
            shlex.quote(str(config["sensors_file"])),
        ]
        notes = str(config.get("notes", "")).strip()
        extra_topics = str(config.get("extra_topics", "")).strip()
        if episode_id:
            args.extend(["--episode-id", shlex.quote(episode_id)])
        if notes:
            args.extend(["--notes", shlex.quote(notes)])
        if extra_topics:
            args.extend(["--extra-topics", shlex.quote(extra_topics)])
        if self.current_session_capture_plan_path is not None:
            args.extend(["--session-plan-file", shlex.quote(str(self.current_session_capture_plan_path))])
        if dry_run:
            args.append("--dry-run")
        return f"source {shlex.quote(ROS_SETUP)} && " + " ".join(args)

    def _build_convert_command(self, config: dict[str, Any], episode_id: str) -> str:
        episode_dir = REPO_ROOT / "raw_episodes" / episode_id
        published_root = REPO_ROOT / "published"
        dataset_id = str(config.get("dataset_id", "")).strip()
        args = [
            shlex.quote(str(CONVERTER_PYTHON)),
            "data_pipeline/convert_episode_bag_to_lerobot.py",
            shlex.quote(str(episode_dir)),
        ]
        if dataset_id:
            args.extend(["--published-dataset-id", shlex.quote(dataset_id)])
        args.extend(["--published-root", shlex.quote(str(published_root))])
        return f"source {shlex.quote(ROS_SETUP)} && " + " ".join(args)

    def _required_record_topics(self, config: dict[str, Any]) -> list[str]:
        topics: list[str] = ["/Spark_enable/lightning"]
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
            topics.extend(
                [
                    "/spark/cameras/wrist/color/image_raw",
                    "/spark/cameras/wrist/depth/image_rect_raw",
                    "/spark/cameras/scene/color/image_raw",
                    "/spark/cameras/scene/depth/image_rect_raw",
                ]
            )
        if config.get("gelsight_enabled", False):
            if config.get("gelsight_enable_left", False):
                topics.append("/spark/tactile/left/color/image_raw")
            if config.get("gelsight_enable_right", False):
                topics.append("/spark/tactile/right/color/image_raw")
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
            "dataset_id",
            "task_name",
            "language_instruction",
            "robot_id",
            "operator",
            "active_arms",
            "sensors_file",
            "wrist_serial_no",
            "scene_serial_no",
            "gelsight_enabled",
            "gelsight_enable_left",
            "gelsight_enable_right",
            "gelsight_left_device_path",
            "gelsight_right_device_path",
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

    def _preview_session_capture_plan(self, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        try:
            return build_session_capture_plan(config, session_id=self.session_id), ""
        except Exception as exc:
            return None, str(exc)
