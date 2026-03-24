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
        QAbstractItemView,
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
        QTableWidget,
        QTableWidgetItem,
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
from data_pipeline.pipeline_utils import role_choices_for_kind


STATUS_STYLES = {
    "green": "background:#d7f2df;color:#15371e;border:1px solid #8ab79a;",
    "yellow": "background:#fff3c4;color:#5b4a06;border:1px solid #d8c670;",
    "red": "background:#f8d6d6;color:#5b1818;border:1px solid #d39b9b;",
    "off": "background:#eceff2;color:#495057;border:1px solid #cbd3db;",
    "info": "background:#e7eef8;color:#29415f;border:1px solid #c3d3ea;",
}

def _device_identifier(device: dict[str, object]) -> str:
    return (
        str(device.get("serial_number", "")).strip()
        or str(device.get("device_path", "")).strip()
        or str(device.get("identifier", "")).strip()
    )


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
        self.notes_target_episode_id = ""

        self.form_widgets: dict[str, QLineEdit | QComboBox | QCheckBox] = {}
        self.health_cards: dict[str, HealthCard] = {}

        self._build_ui()
        self._apply_styles()
        self._load_defaults()

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
        layout.addWidget(self._build_artifacts_box())
        layout.addStretch(1)
        return container

    def _build_task_box(self) -> QWidget:
        box = QGroupBox("Session Metadata")
        form = QFormLayout(box)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        profile_row = QWidget()
        profile_layout = QHBoxLayout(profile_row)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(8)
        self.session_profile_combo = QComboBox()
        self.session_profile_combo.setEditable(True)
        self.load_profile_button = QPushButton("Load")
        self.load_profile_button.clicked.connect(self._load_selected_session_profile)
        self.save_profile_button = QPushButton("Save")
        self.save_profile_button.clicked.connect(self._save_selected_session_profile)
        profile_layout.addWidget(self.session_profile_combo, 1)
        profile_layout.addWidget(self.load_profile_button)
        profile_layout.addWidget(self.save_profile_button)
        form.addRow("Session Profile", profile_row)

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
            ("Robot Type", "robot_id"),
            ("Task Name", "task_name"),
            ("Language", "language_instruction"),
            ("Operator", "operator"),
            ("Active Arms", "active_arms"),
        ]:
            form.addRow(label, self.form_widgets[key])

        self.session_profile_status = QLabel("")
        self.session_profile_status.setWordWrap(True)
        form.addRow("", self.session_profile_status)
        return box

    def _build_sensor_box(self) -> QWidget:
        box = QGroupBox("Discovered Devices")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.form_widgets["sensors_file"] = QLineEdit("data_pipeline/configs/sensors.local.yaml")
        self.form_widgets["viewer_base_url"] = QLineEdit("http://10.33.55.65:3000")
        form.addRow("Sensors File", self.form_widgets["sensors_file"])
        form.addRow("Viewer Base URL", self.form_widgets["viewer_base_url"])
        layout.addLayout(form)

        self.session_devices_table = QTableWidget(0, 5)
        self.session_devices_table.setHorizontalHeaderLabels(["Record", "Kind", "Model", "Identifier", "Role"])
        self.session_devices_table.verticalHeader().setVisible(False)
        self.session_devices_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.session_devices_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_devices_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_devices_table.horizontalHeader().setStretchLastSection(True)
        self.session_devices_table.setColumnWidth(0, 70)
        self.session_devices_table.setColumnWidth(1, 100)
        self.session_devices_table.setColumnWidth(2, 120)
        self.session_devices_table.setColumnWidth(3, 260)
        layout.addWidget(self.session_devices_table)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.discover_devices_button = QPushButton("Discover Devices")
        self.discover_devices_button.clicked.connect(self._discover_session_devices)
        controls.addWidget(self.discover_devices_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        return box

    def _current_device_selection_map(self) -> dict[tuple[str, str], dict[str, object]]:
        selections: dict[tuple[str, str], dict[str, object]] = {}
        for device in self._session_devices():
            key = (str(device.get("kind", "")).strip(), _device_identifier(device))
            if key[1]:
                selections[key] = device
        return selections

    def _discovery_config(self) -> dict[str, object]:
        return {
            "active_arms": str(self._get_field("active_arms")).strip() or "lightning",
            "sensors_file": str(self._get_field("sensors_file")).strip(),
            "session_devices": self._session_devices(),
        }

    def _set_session_devices(self, devices: list[dict[str, object]]) -> None:
        self.session_devices_table.setRowCount(0)
        for device in devices:
            self._append_session_device_row(device)

    def _set_discovered_devices(self, devices: list[dict[str, object]], *, preserve_existing: bool = False) -> None:
        discovered_devices = [dict(device) for device in devices if isinstance(device, dict)]
        if preserve_existing:
            current = self._current_device_selection_map()
            for device in discovered_devices:
                key = (str(device.get("kind", "")).strip(), _device_identifier(device))
                existing = current.get(key)
                if existing is None:
                    continue
                device["enabled"] = bool(existing.get("enabled", False))
                existing_role = str(existing.get("role", "")).strip()
                if existing_role:
                    device["role"] = existing_role
        self._set_session_devices(discovered_devices)

    def _refresh_session_profile_choices(self, *, selected_name: str = "") -> None:
        current_text = selected_name or self.session_profile_combo.currentText().strip()
        self.session_profile_combo.blockSignals(True)
        self.session_profile_combo.clear()
        self.session_profile_combo.addItems(self.backend.list_session_profiles())
        self.session_profile_combo.setEditText(current_text or "default")
        self.session_profile_combo.blockSignals(False)

    def _apply_form_config(self, config: dict[str, object]) -> None:
        self._set_field("dataset_id", str(config.get("dataset_id", "")))
        self._set_field("robot_id", str(config.get("robot_id", "")))
        self._set_field("task_name", str(config.get("task_name", "")))
        self._set_field("language_instruction", str(config.get("language_instruction", "")))
        if "operator" in config:
            self._set_field("operator", str(config.get("operator", "")))
        self._set_field("active_arms", str(config.get("active_arms", "lightning")))
        self._set_field("sensors_file", str(config.get("sensors_file", "data_pipeline/configs/sensors.local.yaml")))
        self._set_field("viewer_base_url", str(config.get("viewer_base_url", "")))
        discovery_config = {
            "active_arms": str(config.get("active_arms", "lightning")),
            "sensors_file": str(config.get("sensors_file", "")),
            "session_devices": list(config.get("session_devices", [])) if isinstance(config.get("session_devices", []), list) else [],
        }
        devices = self.backend.discover_session_devices(discovery_config)
        self._set_discovered_devices(devices, preserve_existing=False)

    def _load_selected_session_profile(self) -> None:
        profile_name = self.session_profile_combo.currentText().strip()
        try:
            config = self.backend.get_session_profile(profile_name)
        except Exception as exc:
            self.session_profile_status.setText(str(exc))
            return
        self._apply_form_config(config)
        self._refresh_session_profile_choices(selected_name=profile_name or "default")
        self.session_profile_status.setText(f"Loaded session profile: {profile_name or 'default'}")

    def _save_selected_session_profile(self) -> None:
        profile_name = self.session_profile_combo.currentText().strip()
        try:
            saved_name = self.backend.save_session_profile(profile_name, self._config())
        except Exception as exc:
            self.session_profile_status.setText(str(exc))
            return
        self._refresh_session_profile_choices(selected_name=saved_name)
        self.session_profile_status.setText(f"Saved session profile: {saved_name}")

    def _append_session_device_row(self, device: dict[str, object]) -> None:
        row = self.session_devices_table.rowCount()
        self.session_devices_table.insertRow(row)

        enabled = QCheckBox()
        enabled.setChecked(bool(device.get("enabled", False)))
        enabled.setStyleSheet("margin-left:18px;")
        self.session_devices_table.setCellWidget(row, 0, enabled)

        kind_value = str(device.get("kind", "device")).strip() or "device"
        kind_item = QTableWidgetItem(kind_value)
        self.session_devices_table.setItem(row, 1, kind_item)

        model_item = QTableWidgetItem(str(device.get("model", "")).strip())
        self.session_devices_table.setItem(row, 2, model_item)

        identifier_value = _device_identifier(device)
        identifier_item = QTableWidgetItem(identifier_value)
        self.session_devices_table.setItem(row, 3, identifier_item)

        role_combo = QComboBox()
        role_choices = role_choices_for_kind(kind_value)
        role_combo.addItems(role_choices)
        role_value = str(device.get("role", "")).strip()
        if role_value and role_combo.findText(role_value) < 0:
            role_combo.addItem(role_value)
        role_combo.setCurrentText(role_value)
        self.session_devices_table.setCellWidget(row, 4, role_combo)

        identifier_item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "kind": kind_value,
                "identifier": identifier_value,
                "model": device.get("model"),
                "sensor_id": device.get("sensor_id"),
                "attached_to": device.get("attached_to"),
                "mount_site": device.get("mount_site"),
                "calibration_ref": device.get("calibration_ref"),
                "serial_number": str(device.get("serial_number", "")).strip(),
                "device_path": str(device.get("device_path", "")).strip(),
            },
        )

    def _session_devices(self) -> list[dict[str, object]]:
        devices: list[dict[str, object]] = []
        for row in range(self.session_devices_table.rowCount()):
            enabled_widget = self.session_devices_table.cellWidget(row, 0)
            kind_item = self.session_devices_table.item(row, 1)
            identifier_item = self.session_devices_table.item(row, 3)
            role_widget = self.session_devices_table.cellWidget(row, 4)
            if not isinstance(enabled_widget, QCheckBox):
                continue
            if not isinstance(kind_item, QTableWidgetItem):
                continue
            if not isinstance(identifier_item, QTableWidgetItem):
                continue
            if not isinstance(role_widget, QComboBox):
                continue
            metadata = identifier_item.data(Qt.ItemDataRole.UserRole) if identifier_item is not None else {}
            if not isinstance(metadata, dict):
                metadata = {}

            kind = kind_item.text().strip()
            identifier = identifier_item.text().strip()
            role = role_widget.currentText().strip()
            device: dict[str, object] = {
                "kind": kind,
                "identifier": identifier,
                "enabled": enabled_widget.isChecked(),
                "role": role,
            }
            for key in ("model", "sensor_id", "attached_to", "mount_site", "calibration_ref"):
                value = metadata.get(key)
                if value not in {"", None}:
                    device[key] = value
            if kind == "realsense":
                device["serial_number"] = str(metadata.get("serial_number", "")).strip() or identifier
            elif kind == "gelsight":
                device["device_path"] = str(metadata.get("device_path", "")).strip() or identifier
                serial_number = str(metadata.get("serial_number", "")).strip()
                if serial_number:
                    device["serial_number"] = serial_number
            devices.append(device)
        return devices

    def _discover_session_devices(self) -> None:
        devices = self.backend.discover_session_devices(self._discovery_config())
        self._set_discovered_devices(devices, preserve_existing=True)

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

        notes_container = QWidget()
        notes_layout = QVBoxLayout(notes_container)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(6)
        self.latest_episode_notes_text = QPlainTextEdit()
        self.latest_episode_notes_text.setPlaceholderText("Optional post-take notes for the latest episode.")
        self.latest_episode_notes_text.setMaximumHeight(110)
        self.latest_episode_notes_text.textChanged.connect(self._update_episode_notes_button_state)
        notes_layout.addWidget(self.latest_episode_notes_text)
        notes_row = QHBoxLayout()
        notes_row.setContentsMargins(0, 0, 0, 0)
        notes_row.setSpacing(8)
        self.save_episode_notes_button = QPushButton("Save Episode Notes")
        self.save_episode_notes_button.clicked.connect(self._save_latest_episode_notes)
        self.latest_episode_notes_status = QLabel("")
        self.latest_episode_notes_status.setWordWrap(True)
        notes_row.addWidget(self.save_episode_notes_button)
        notes_row.addWidget(self.latest_episode_notes_status, 1)
        notes_layout.addLayout(notes_row)
        artifacts_layout.addRow("Post-take Notes", notes_container)
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

    def _load_defaults(self) -> None:
        self._refresh_session_profile_choices(selected_name="default")
        self._apply_form_config(self.backend.default_form_config())
        self.session_profile_status.setText("Loaded built-in default session profile.")

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
        session_devices = self._session_devices()
        enabled_realsense = [
            device for device in session_devices
            if bool(device.get("enabled", False)) and str(device.get("kind", "")).strip() == "realsense"
        ]
        enabled_gelsights = [
            device for device in session_devices
            if bool(device.get("enabled", False)) and str(device.get("kind", "")).strip() == "gelsight"
        ]

        return {
            "dataset_id": self._get_field("dataset_id"),
            "robot_id": self._get_field("robot_id"),
            "task_name": self._get_field("task_name"),
            "language_instruction": self._get_field("language_instruction"),
            "operator": self._get_field("operator"),
            "active_arms": self._get_field("active_arms"),
            "sensors_file": self._get_field("sensors_file"),
            "session_devices": session_devices,
            "realsense_enabled": bool(enabled_realsense),
            "gelsight_enabled": bool(enabled_gelsights),
            "viewer_base_url": self._get_field("viewer_base_url"),
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

    def _save_latest_episode_notes(self) -> None:
        self.backend.save_latest_episode_notes(self.latest_episode_notes_text.toPlainText())
        self._update_episode_notes_status(self.backend.snapshot(self._config()))

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
        latest_episode_id = str(snapshot.get("latest_episode_id") or "")
        self._sync_episode_notes_target(latest_episode_id)
        self.latest_episode_label.setText(latest_episode_id)
        self.latest_dataset_label.setText(snapshot.get("latest_dataset_id") or "")
        self.latest_viewer_label.setText(snapshot.get("latest_viewer_url") or "")
        self._update_episode_notes_status(snapshot)
        self._render_health(snapshot.get("health", {}))
        self._render_logs(snapshot)
        self._render_output(snapshot)
        self._update_button_states(snapshot)

    def _sync_episode_notes_target(self, latest_episode_id: str) -> None:
        if latest_episode_id == self.notes_target_episode_id:
            return
        self.notes_target_episode_id = latest_episode_id
        self.latest_episode_notes_text.blockSignals(True)
        self.latest_episode_notes_text.setPlainText("")
        self.latest_episode_notes_text.blockSignals(False)
        self.latest_episode_notes_status.setText("")
        self._update_episode_notes_button_state()

    def _update_episode_notes_status(self, snapshot: dict[str, object]) -> None:
        latest_note_output = str(snapshot.get("latest_episode_notes_output") or "").strip()
        if latest_note_output:
            self.latest_episode_notes_status.setText(latest_note_output)
            return
        if self.notes_target_episode_id:
            self.latest_episode_notes_status.setText("Optional. Saved to this episode only.")
        else:
            self.latest_episode_notes_status.setText("Record an episode first.")

    def _update_episode_notes_button_state(self) -> None:
        has_episode = bool(self.notes_target_episode_id)
        has_text = bool(self.latest_episode_notes_text.toPlainText().strip())
        recorder_running = self.backend.processes["recorder"].state == "running"
        self.save_episode_notes_button.setEnabled(has_episode and has_text and not recorder_running)

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
        if snapshot.get("latest_episode_notes_output"):
            lines.extend(["Episode notes:", str(snapshot["latest_episode_notes_output"])])
        rendered = "\n".join(lines).strip()
        if rendered == self.last_output_render:
            return
        self.last_output_render = rendered
        self.output_text.setPlainText(rendered)
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_button_states(self, snapshot: dict[str, object]) -> None:
        current_config = self._config()
        session_state = str(snapshot.get("session_state", "idle"))
        validation_state = str(snapshot.get("validation_state", "not_run"))
        processes = snapshot.get("processes", {})
        recorder_state = str(processes.get("recorder", {}).get("state", "stopped"))
        converter_state = str(processes.get("converter", {}).get("state", "stopped"))
        recording_ready = bool(snapshot.get("latest_episode_id")) and snapshot.get("latest_recording_ok") is True
        recording_check_running = bool(snapshot.get("recording_check_running"))
        viewer_available = self.backend.viewer_target_available(current_config)
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

            if name == "realsense_contract" and not bool(current_config["realsense_enabled"]):
                start_enabled = False
                stop_enabled = False

            if name == "gelsight_contract" and not bool(current_config["gelsight_enabled"]):
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
