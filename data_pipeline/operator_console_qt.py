#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import socket
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QSocketNotifier, QTimer, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPushButton,
        QPlainTextEdit,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - runtime guard only
    print(
        "PySide6 is not installed. Activate .venv and run: "
        "pip install -r data_pipeline/requirements-operator-console.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.operator_console_backend import OperatorConsoleBackend


STATUS_STYLES = {
    "green": "background:#d7f2df;color:#15371e;border:1px solid #8ab79a;",
    "yellow": "background:#fff3c4;color:#5b4a06;border:1px solid #d8c670;",
    "red": "background:#f8d6d6;color:#5b1818;border:1px solid #d39b9b;",
    "off": "background:#eceff2;color:#495057;border:1px solid #cbd3db;",
    "info": "background:#e7eef8;color:#29415f;border:1px solid #c3d3ea;",
}


def apply_chip_style(label: QLabel, tone: str) -> None:
    label.setStyleSheet(
        STATUS_STYLES.get(tone, STATUS_STYLES["off"]) + "border-radius:10px;padding:5px 10px;font-weight:600;"
    )


def card_status_text(status: str, summary: str) -> tuple[str, str]:
    lowered = summary.lower()
    if status == "green":
        return "Healthy", "green"
    if status == "red":
        return "Failed", "red"
    if status == "off":
        return "Idle", "off"
    if "starting" in lowered:
        return "Starting", "yellow"
    if "static" in lowered:
        return "Static", "yellow"
    if "ready" in lowered:
        return "Ready", "yellow"
    if "complete" in lowered:
        return "Complete", "yellow"
    if "running" in lowered:
        return "Running", "yellow"
    return "Attention", "yellow"


class HealthCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.status_chip = QLabel("Idle")
        self.status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_chip.setMinimumWidth(92)
        apply_chip_style(self.status_chip, "off")
        title_row.addWidget(self.status_chip)
        layout.addLayout(title_row)

        self.summary_label = QLabel("Unknown")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("cardSummary")
        layout.addWidget(self.summary_label)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setObjectName("cardDetails")
        layout.addWidget(self.details_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)
        button_row.setSpacing(6)
        self.primary_button = QPushButton("Start")
        self.secondary_button = QPushButton("Stop")
        button_row.addWidget(self.primary_button)
        button_row.addWidget(self.secondary_button)
        layout.addLayout(button_row)

    def set_status(self, status: str, summary: str, details: list[str]) -> None:
        chip_text, chip_tone = card_status_text(status, summary)
        self.status_chip.setText(chip_text)
        apply_chip_style(self.status_chip, chip_tone)
        self.summary_label.setText(summary)
        self.details_label.setText("\n".join(details) if details else "")


class OperatorConsoleQtWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.backend = OperatorConsoleBackend()
        self.setWindowTitle("Operator Console")
        self.resize(1820, 1040)

        self.last_log_render = ""
        self.last_output_render = ""

        self.form_widgets: dict[str, QLineEdit | QComboBox | QCheckBox] = {}
        self.health_cards: dict[str, HealthCard] = {}

        self._build_ui()
        self._apply_styles()
        self._load_first_preset()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(2, 2, 2, 2)
        left_layout.setSpacing(12)
        left_layout.addWidget(self._make_scroll_area(self._build_form_panel()), 1)
        splitter.addWidget(left_panel)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(2, 2, 2, 2)
        center_layout.setSpacing(12)
        center_layout.addWidget(self._make_scroll_area(self._build_health_panel()), 1)
        splitter.addWidget(center_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(2, 2, 2, 2)
        right_layout.setSpacing(12)
        right_layout.addWidget(self._build_command_panel())
        right_layout.addWidget(self._build_logs_panel(), 3)
        right_layout.addWidget(self._build_output_panel(), 2)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([480, 560, 760])

    def _make_scroll_area(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _build_form_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 6)
        layout.setSpacing(12)

        layout.addWidget(self._build_task_box())
        layout.addWidget(self._build_sensor_box())
        layout.addWidget(self._build_session_actions_box())
        layout.addWidget(self._build_optional_box())
        layout.addWidget(self._build_artifacts_box())
        layout.addStretch(1)
        return container

    def _build_task_box(self) -> QWidget:
        box = QGroupBox("Preset & Task")
        form = QFormLayout(box)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.preset_combo = QComboBox()
        for preset_id, _label in self.backend.list_presets():
            self.preset_combo.addItem(preset_id)
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        form.addRow("Preset", self.preset_combo)

        self.form_widgets["dataset_id"] = QLineEdit()
        self.form_widgets["robot_id"] = QLineEdit()
        self.form_widgets["task_name"] = QLineEdit()
        self.form_widgets["language_instruction"] = QLineEdit()
        self.form_widgets["operator"] = QLineEdit(os.environ.get("USER", ""))
        active_arms = QComboBox()
        active_arms.addItems(["lightning", "thunder", "lightning,thunder"])
        self.form_widgets["active_arms"] = active_arms

        for label, key in [
            ("Dataset ID", "dataset_id"),
            ("Robot ID", "robot_id"),
            ("Task Name", "task_name"),
            ("Language", "language_instruction"),
            ("Operator", "operator"),
            ("Active Arms", "active_arms"),
        ]:
            form.addRow(label, self.form_widgets[key])
        return box

    def _build_sensor_box(self) -> QWidget:
        box = QGroupBox("Sensor Inputs")
        form = QFormLayout(box)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.form_widgets["sensors_file"] = QLineEdit("data_pipeline/configs/sensors.local.yaml")
        self.form_widgets["wrist_serial_no"] = QLineEdit()
        self.form_widgets["scene_serial_no"] = QLineEdit()
        self.form_widgets["gelsight_left_device_path"] = QLineEdit()
        self.form_widgets["viewer_base_url"] = QLineEdit("http://10.33.55.65:3000")

        for label, key in [
            ("Sensors File", "sensors_file"),
            ("Wrist Serial", "wrist_serial_no"),
            ("Scene Serial", "scene_serial_no"),
            ("GelSight Left Path", "gelsight_left_device_path"),
            ("Viewer Base URL", "viewer_base_url"),
        ]:
            form.addRow(label, self.form_widgets[key])

        gelsight_checkbox = QCheckBox("Enable GelSight")
        self.form_widgets["gelsight_enabled"] = gelsight_checkbox
        form.addRow("", gelsight_checkbox)
        return box

    def _build_optional_box(self) -> QWidget:
        box = QGroupBox("Optional")
        form = QFormLayout(box)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.form_widgets["notes"] = QLineEdit()
        self.form_widgets["extra_topics"] = QLineEdit()
        form.addRow("Notes", self.form_widgets["notes"])
        form.addRow("Extra Topics", self.form_widgets["extra_topics"])
        return box

    def _build_session_actions_box(self) -> QWidget:
        box = QGroupBox("Session Actions")
        layout = QGridLayout(box)
        layout.setSpacing(8)
        self.start_session_button = QPushButton("Start Session")
        self.start_session_button.clicked.connect(self._start_session)
        self.stop_session_button = QPushButton("Stop Session")
        self.stop_session_button.clicked.connect(self._stop_session)
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(self._validate)
        layout.addWidget(self.start_session_button, 0, 0)
        layout.addWidget(self.stop_session_button, 0, 1)
        layout.addWidget(self.validate_button, 1, 0, 1, 2)
        return box

    def _build_artifacts_box(self) -> QWidget:
        artifacts_box = QGroupBox("Latest Artifacts")
        artifacts_layout = QFormLayout(artifacts_box)
        artifacts_layout.setSpacing(8)
        self.latest_episode_label = QLabel("")
        self.latest_episode_label.setWordWrap(True)
        self.latest_episode_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.latest_dataset_label = QLabel("")
        self.latest_dataset_label.setWordWrap(True)
        self.latest_dataset_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.latest_viewer_label = QLabel("")
        self.latest_viewer_label.setWordWrap(True)
        self.latest_viewer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        artifacts_layout.addRow("Episode", self.latest_episode_label)
        artifacts_layout.addRow("Dataset", self.latest_dataset_label)
        artifacts_layout.addRow("Viewer", self.latest_viewer_label)
        return artifacts_box

    def _build_health_panel(self) -> QWidget:
        box = QGroupBox("Subsystem Health")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 14, 10, 14)
        display_names = {
            "spark_devices": "SPARK Devices",
            "teleop_gui": "Teleop GUI",
            "realsense_contract": "RealSense",
            "gelsight_contract": "GelSight",
            "recorder": "Recorder",
            "converter": "Converter",
        }
        for name in ["spark_devices", "teleop_gui", "realsense_contract", "gelsight_contract", "recorder", "converter"]:
            card = HealthCard(display_names[name])
            card.primary_button.clicked.connect(lambda _checked=False, process=name: self._start_named_process(process))
            card.secondary_button.clicked.connect(lambda _checked=False, process=name: self._stop_named_process(process))
            self.health_cards[name] = card
            layout.addWidget(card)
        layout.addStretch(1)
        return box

    def _build_command_panel(self) -> QWidget:
        box = QGroupBox("Selected Process")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        self.selected_process_label = QLabel("Process: spark_devices")
        self.selected_process_label.setObjectName("selectedProcessLabel")
        layout.addWidget(self.selected_process_label)
        self.command_label = QLabel("")
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.command_label.setMaximumHeight(66)
        layout.addWidget(self.command_label)
        return box

    def _build_logs_panel(self) -> QWidget:
        box = QGroupBox("Process Logs")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        self.log_process_combo = QComboBox()
        for name in self.backend.processes.keys():
            self.log_process_combo.addItem(name)
        layout.addWidget(self.log_process_combo)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)
        return box

    def _build_output_panel(self) -> QWidget:
        box = QGroupBox("Action Output")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text, 1)
        return box

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #eef2f6;
            }
            QGroupBox {
                font-weight: 700;
                border: 1px solid #d8dde6;
                border-radius: 16px;
                margin-top: 10px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 4px;
                color: #223044;
            }
            QFrame#healthCard {
                background: #fbfcfe;
                border: 1px solid #dde3ec;
                border-radius: 16px;
            }
            QLabel#cardTitle {
                font-size: 15px;
                font-weight: 700;
                color: #1f2a37;
            }
            QLabel#cardSummary {
                color: #233245;
                font-weight: 600;
            }
            QLabel#cardDetails {
                color: #5d6a79;
            }
            QLabel#selectedProcessLabel {
                font-weight: 600;
                color: #5d6a79;
            }
            QLineEdit, QPlainTextEdit {
                border: 1px solid #cfd6e1;
                border-radius: 10px;
                padding: 8px 10px;
                background: #ffffff;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #cfd6e1;
                background: #ffffff;
                selection-background-color: #edf4ff;
                selection-color: #1f2a37;
            }
            QPushButton {
                min-height: 34px;
                border: 1px solid #c9d4e2;
                border-radius: 10px;
                background: #ffffff;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #edf4ff;
            }
            QPushButton:disabled {
                color: #9aa3af;
                background: #f5f6f8;
            }
            """
        )

    def _load_first_preset(self) -> None:
        if self.preset_combo.count() == 0:
            return
        self._apply_preset(self.preset_combo.currentText())

    def _apply_preset(self, preset_id: str) -> None:
        if not preset_id:
            return
        preset = self.backend.get_preset(preset_id)
        self._set_field("dataset_id", str(preset.get("dataset_id", "")))
        self._set_field("robot_id", str(preset.get("robot_id", "")))
        self._set_field("task_name", str(preset.get("task_name", "")))
        self._set_field("language_instruction", str(preset.get("language_instruction", "")))
        if preset.get("operator"):
            self._set_field("operator", str(preset.get("operator", "")))
        self._set_field("active_arms", str(preset.get("active_arms", "lightning")))
        self._set_field("sensors_file", str(preset.get("sensors_file", "data_pipeline/configs/sensors.local.yaml")))
        self._set_field("wrist_serial_no", str(preset.get("realsense", {}).get("wrist_serial_no", "")))
        self._set_field("scene_serial_no", str(preset.get("realsense", {}).get("scene_serial_no", "")))
        self._set_field("gelsight_enabled", bool(preset.get("gelsight", {}).get("enabled", False)))
        self._set_field("gelsight_left_device_path", str(preset.get("gelsight", {}).get("left_device_path", "")))
        self._set_field("viewer_base_url", str(preset.get("viewer_base_url", "")))
        self._set_field("notes", "")
        self._set_field("extra_topics", "")

    def _set_field(self, key: str, value: str | bool) -> None:
        widget = self.form_widgets[key]
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif isinstance(widget, QComboBox):
            index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                widget.setEditText(str(value))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))

    def _get_field(self, key: str) -> str | bool:
        widget = self.form_widgets[key]
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        raise TypeError(f"Unsupported widget type for {key}")

    def _config(self) -> dict[str, object]:
        return {
            "preset_id": self.preset_combo.currentText().strip(),
            "dataset_id": self._get_field("dataset_id"),
            "robot_id": self._get_field("robot_id"),
            "task_name": self._get_field("task_name"),
            "language_instruction": self._get_field("language_instruction"),
            "operator": self._get_field("operator"),
            "active_arms": self._get_field("active_arms"),
            "sensors_file": self._get_field("sensors_file"),
            "wrist_serial_no": self._get_field("wrist_serial_no"),
            "scene_serial_no": self._get_field("scene_serial_no"),
            "realsense_enabled": True,
            "gelsight_enabled": bool(self._get_field("gelsight_enabled")),
            "gelsight_enable_left": bool(self._get_field("gelsight_enabled")),
            "gelsight_enable_right": False,
            "gelsight_left_device_path": self._get_field("gelsight_left_device_path"),
            "gelsight_right_device_path": "",
            "viewer_base_url": self._get_field("viewer_base_url"),
            "notes": self._get_field("notes"),
            "extra_topics": self._get_field("extra_topics"),
        }

    def _start_session(self) -> None:
        self.backend.start_session(self._config())
        self._focus_process_logs("spark_devices")

    def _stop_session(self) -> None:
        self.backend.stop_session()

    def _validate(self) -> None:
        self.backend.start_validation(self._config())

    def _start_recording(self) -> None:
        self.backend.start_recording(self._config())
        self._focus_process_logs("recorder")

    def _stop_recording(self) -> None:
        self.backend.stop_recording()
        self._focus_process_logs("recorder")

    def _convert_latest(self) -> None:
        self.backend.start_conversion(self._config())
        self._focus_process_logs("converter")

    def _open_viewer(self) -> None:
        self.backend.open_viewer(self._config())
        self._focus_process_logs("viewer_server")

    def _start_named_process(self, name: str) -> None:
        self.backend.start_named_process(name, self._config())
        if name in self.backend.processes:
            self._focus_process_logs(name)

    def _stop_named_process(self, name: str) -> None:
        self.backend.stop_named_process(name)
        if name in self.backend.processes:
            self._focus_process_logs(name)

    def _tick(self) -> None:
        config = self._config()
        self.backend.request_health_refresh(config)
        snapshot = self.backend.snapshot(config)
        self.latest_episode_label.setText(snapshot.get("latest_episode_id") or "")
        self.latest_dataset_label.setText(snapshot.get("latest_dataset_id") or "")
        self.latest_viewer_label.setText(snapshot.get("latest_viewer_url") or "")
        self._render_health(snapshot.get("health", {}))
        self._render_logs(snapshot)
        self._render_output(snapshot)
        self._update_button_states(snapshot)

    def _render_health(self, health: dict[str, dict[str, object]]) -> None:
        for name, card in self.health_cards.items():
            status_card = health.get(name, {"status": "off", "summary": "Unknown", "details": []})
            card.set_status(
                str(status_card.get("status", "off")),
                str(status_card.get("summary", "Unknown")),
                list(status_card.get("details", [])),
            )

    def _render_logs(self, snapshot: dict[str, object]) -> None:
        selected = self.log_process_combo.currentText().strip() or "spark_devices"
        logs = self.backend.get_process_logs(selected)
        rendered = "\n".join(logs[-200:])
        process = snapshot.get("processes", {}).get(selected, {})
        self.selected_process_label.setText(f"Process: {selected}")
        self.command_label.setText(str(process.get("command", "")))
        if rendered == self.last_log_render:
            return
        self.last_log_render = rendered
        self.log_text.setPlainText(rendered)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _focus_process_logs(self, process_name: str) -> None:
        index = self.log_process_combo.findText(process_name)
        if index >= 0:
            self.log_process_combo.setCurrentIndex(index)

    def _render_output(self, snapshot: dict[str, object]) -> None:
        lines = [
            f"Session state: {snapshot.get('session_state', 'idle')}",
            f"Validation state: {snapshot.get('validation_state', 'not_run')}",
            "",
        ]
        if snapshot.get("last_action_error"):
            lines.extend(["Last error:", str(snapshot["last_action_error"]), ""])
        if snapshot.get("last_validation_output"):
            lines.extend(["Validate output:", str(snapshot["last_validation_output"]), ""])
        if snapshot.get("latest_recording_check_output"):
            lines.extend(["Recording check:", str(snapshot["latest_recording_check_output"]), ""])
        if snapshot.get("latest_conversion_output"):
            lines.extend(["Convert output:", str(snapshot["latest_conversion_output"])])
        rendered = "\n".join(lines).strip()
        if rendered == self.last_output_render:
            return
        self.last_output_render = rendered
        self.output_text.setPlainText(rendered)
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_button_states(self, snapshot: dict[str, object]) -> None:
        session_state = str(snapshot.get("session_state", "idle"))
        validation_state = str(snapshot.get("validation_state", "not_run"))
        processes = snapshot.get("processes", {})
        recorder_state = str(processes.get("recorder", {}).get("state", "stopped"))
        converter_state = str(processes.get("converter", {}).get("state", "stopped"))
        recording_ready = bool(snapshot.get("latest_episode_id")) and snapshot.get("latest_recording_ok") is True
        recording_check_running = bool(snapshot.get("recording_check_running"))
        viewer_available = self.backend.viewer_target_available(self._config())
        live_states = {"running", "starting", "stopping"}
        core_running = any(
            str(processes.get(name, {}).get("state", "stopped")) in live_states
            for name in ("spark_devices", "teleop_gui", "realsense_contract", "gelsight_contract")
        )
        work_running = any(
            str(processes.get(name, {}).get("state", "stopped")) in live_states
            for name in ("recorder", "converter")
        )
        session_running = core_running or work_running
        can_record = validation_state == "passed" and core_running and recorder_state != "running"

        self.start_session_button.setEnabled(not session_running)
        self.stop_session_button.setEnabled(session_running)
        self.validate_button.setEnabled(core_running and validation_state != "running")

        for name, card in self.health_cards.items():
            state = str(processes.get(name, {}).get("state", "stopped"))
            start_enabled = state not in {"running", "starting", "stopping"}
            stop_enabled = state in {"running", "starting", "failed"}

            if name == "gelsight_contract" and not bool(self._get_field("gelsight_enabled")):
                start_enabled = False
                stop_enabled = False

            if name == "recorder":
                self._update_recorder_card(card, recorder_state, can_record, recording_check_running)
                continue
            if name == "converter":
                self._update_converter_card(card, converter_state, recording_ready, viewer_available)
                continue

            card.primary_button.setText("Start")
            card.primary_button.clicked.disconnect() if False else None
            card.primary_button.setEnabled(start_enabled)
            card.secondary_button.setText("Stop")
            card.secondary_button.setEnabled(stop_enabled)

    def _update_recorder_card(self, card: HealthCard, recorder_state: str, can_record: bool, recording_check_running: bool) -> None:
        card.primary_button.clicked.disconnect() if False else None
        card.secondary_button.clicked.disconnect() if False else None
        self._rebind_button(card.primary_button, "Record", self._start_recording)
        self._rebind_button(card.secondary_button, "Stop", self._stop_recording)
        if recorder_state == "running":
            card.primary_button.setEnabled(False)
            card.secondary_button.setEnabled(True)
            return
        if recording_check_running:
            self._rebind_button(card.primary_button, "Analyzing", self._start_recording)
            self._rebind_button(card.secondary_button, "Wait", self._stop_recording)
            card.primary_button.setEnabled(False)
            card.secondary_button.setEnabled(False)
            return
        card.primary_button.setEnabled(bool(can_record))
        card.secondary_button.setEnabled(False)

    def _update_converter_card(self, card: HealthCard, converter_state: str, recording_ready: bool, viewer_available: bool) -> None:
        if converter_state == "running":
            self._rebind_button(card.primary_button, "Convert", self._convert_latest)
            self._rebind_button(card.secondary_button, "Stop", lambda: self._stop_named_process("converter"))
            card.primary_button.setEnabled(False)
            card.secondary_button.setEnabled(True)
            return
        if recording_ready:
            self._rebind_button(card.primary_button, "Convert", self._convert_latest)
            self._rebind_button(card.secondary_button, "Open Viewer", self._open_viewer)
            card.primary_button.setEnabled(True)
            card.secondary_button.setEnabled(bool(viewer_available))
            return
        if viewer_available:
            self._rebind_button(card.primary_button, "Open Viewer", self._open_viewer)
            self._rebind_button(card.secondary_button, "Stop", lambda: self._stop_named_process("converter"))
            card.primary_button.setEnabled(True)
            card.secondary_button.setEnabled(False)
            return
        self._rebind_button(card.primary_button, "Convert", self._convert_latest)
        self._rebind_button(card.secondary_button, "Stop", lambda: self._stop_named_process("converter"))
        card.primary_button.setEnabled(False)
        card.secondary_button.setEnabled(False)

    def _rebind_button(self, button: QPushButton, text: str, callback) -> None:
        try:
            button.clicked.disconnect()
        except Exception:
            pass
        button.setText(text)
        button.clicked.connect(callback)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.backend.stop_session()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    signal_read, signal_write = socket.socketpair()
    signal_read.setblocking(False)
    signal_write.setblocking(False)

    previous_wakeup_fd = signal.set_wakeup_fd(signal_write.fileno())

    def _qt_signal_handler(_signum, _frame) -> None:
        return None

    signal.signal(signal.SIGINT, _qt_signal_handler)
    signal.signal(signal.SIGTERM, _qt_signal_handler)

    notifier = QSocketNotifier(signal_read.fileno(), QSocketNotifier.Type.Read)

    def _drain_signal_fd() -> None:
        try:
            signal_read.recv(128)
        except BlockingIOError:
            pass
        app.quit()

    notifier.activated.connect(_drain_signal_fd)
    window = OperatorConsoleQtWindow()
    window.show()
    try:
        return app.exec()
    finally:
        notifier.setEnabled(False)
        signal.set_wakeup_fd(previous_wakeup_fd)
        signal_read.close()
        signal_write.close()


if __name__ == "__main__":
    raise SystemExit(main())
