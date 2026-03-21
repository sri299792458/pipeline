#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import threading
import time
import webbrowser
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


ROS_SETUP = "/opt/ros/jazzy/setup.bash"
TELEOP_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
CONVERTER_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
SYSTEM_PYTHON = "/usr/bin/python3"
PRESETS_PATH = REPO_ROOT / "data_pipeline" / "configs" / "operator_console_presets.yaml"
STATE_DIR = REPO_ROOT / ".operator_console"


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
        }
        self.process_lock = threading.Lock()
        self.last_health: dict[str, dict[str, Any]] = {}
        self.health_refresh_in_flight = False
        self.last_validation_ok = False
        self.last_validation_output = ""
        self.last_validation_signature = ""
        self.last_action_error = ""
        self.latest_episode_id: str | None = None
        self.latest_dataset_id: str | None = None
        self.latest_viewer_url: str | None = None
        self.latest_conversion_output = ""
        self.pending_conversion_dataset_id: str | None = None
        self.topic_probe_cache: dict[str, tuple[float, bool]] = {}
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_events: list[dict[str, Any]] = []
        self.session_log_dir = STATE_DIR / "sessions"
        self.session_log_dir.mkdir(parents=True, exist_ok=True)
        self.session_log_path = self.session_log_dir / f"session-{self.session_id}.json"
        self._persist_session_log()

    STARTUP_GRACE_S = {
        "spark_devices": 10.0,
        "teleop_gui": 12.0,
        "realsense_contract": 18.0,
        "gelsight_contract": 12.0,
    }

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
        return {
            "session_state": self.session_state(config),
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
        }

    def get_process_logs(self, name: str) -> list[str]:
        process = self.processes.get(name)
        if process is None:
            return []
        return process.get_logs()

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
        self._record_event("stop_session", {})

    def start_validation(self, config: dict[str, Any]) -> None:
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
        self.latest_episode_id = episode_id
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
        dataset_id = self.latest_dataset_id or config["dataset_id"]
        viewer_base_url = str(config.get("viewer_base_url", "")).strip().rstrip("/")
        if not viewer_base_url:
            self.last_action_error = "Viewer base URL is empty."
            return
        info_path = REPO_ROOT / "published" / dataset_id / "meta" / "info.json"
        if not info_path.exists():
            self.last_action_error = f"Published dataset info not found: {info_path}"
            return
        with info_path.open("r", encoding="utf-8") as handle:
            info = json.load(handle)
        episode_index = max(int(info.get("total_episodes", 1)) - 1, 0)
        url = f"{viewer_base_url}/local/{dataset_id}/episode_{episode_index}"
        self.latest_viewer_url = url
        webbrowser.open(url)
        self._record_event("open_viewer", {"url": url})

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
        return self._build_health_card(
            process_name="spark_devices",
            live_topics=live_topics,
            required_topics=required_topics,
            sample_topics=sample_topics,
        )

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
        return {"status": "off", "summary": "Recorder not running", "details": []}

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
            topic for topic in sample_topics if topic in live_topics and not self._topic_has_message_cached(topic)
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

    def _topic_has_message(self, topic: str, timeout_s: float = 1.0) -> bool:
        try:
            result = self._run_ros_command(
                f"ros2 topic echo --once {shlex.quote(topic)}",
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def _topic_has_message_cached(self, topic: str, timeout_s: float = 0.8, ttl_s: float = 5.0) -> bool:
        cached = self.topic_probe_cache.get(topic)
        now = time.time()
        if cached is not None:
            ts, value = cached
            if (now - ts) < ttl_s:
                return value
        value = self._topic_has_message(topic, timeout_s=timeout_s)
        self.topic_probe_cache[topic] = (now, value)
        return value

    def _run_validation(self, config: dict[str, Any]) -> None:
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

    def _probe_required_streams(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        active_arms = self._active_arm_list(config)
        if active_arms:
            spark_topic = f"/Spark_angle/{active_arms[0]}"
            if not self._topic_has_message(spark_topic, timeout_s=2.5):
                errors.append(f"Timed out waiting for Spark stream: {spark_topic}")
            robot_topic = f"/spark/{active_arms[0]}/robot/joint_state"
            if not self._topic_has_message(robot_topic, timeout_s=2.5):
                errors.append(f"Timed out waiting for robot state: {robot_topic}")
        if config.get("realsense_enabled", True):
            for topic in [
                "/spark/cameras/wrist/color/image_raw",
                "/spark/cameras/scene/color/image_raw",
            ]:
                if not self._topic_has_message(topic, timeout_s=2.5):
                    errors.append(f"Timed out waiting for camera stream: {topic}")
        if config.get("gelsight_enabled", False):
            if config.get("gelsight_enable_left", False):
                topic = "/spark/tactile/left/color/image_raw"
                if not self._topic_has_message(topic, timeout_s=2.5):
                    errors.append(f"Timed out waiting for tactile stream: {topic}")
            if config.get("gelsight_enable_right", False):
                topic = "/spark/tactile/right/color/image_raw"
                if not self._topic_has_message(topic, timeout_s=2.5):
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
            try:
                if sigint:
                    os.killpg(process.process.pid, signal.SIGINT)
                else:
                    os.killpg(process.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.state = "stopping"

    def _drain_logs(self, name: str, popen: subprocess.Popen[str]) -> None:
        process = self.processes[name]
        assert popen.stdout is not None
        for line in popen.stdout:
            process.append_log(line)
        exit_code = popen.wait()
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
            self.pending_conversion_dataset_id = None

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
        if dry_run:
            args.append("--dry-run")
        return f"source {shlex.quote(ROS_SETUP)} && " + " ".join(args)

    def _build_convert_command(self, config: dict[str, Any], episode_id: str) -> str:
        episode_dir = REPO_ROOT / "raw_episodes" / episode_id
        published_root = REPO_ROOT / "published"
        return (
            f"{shlex.quote(str(CONVERTER_PYTHON))} "
            f"data_pipeline/convert_episode_bag_to_lerobot.py "
            f"{shlex.quote(str(episode_dir))} "
            f"--published-root {shlex.quote(str(published_root))}"
        )

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
        }
        with self.session_log_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
