#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.operator_console_backend import OperatorConsoleBackend


STATUS_COLORS = {
    "green": "#cfead6",
    "yellow": "#f6efbf",
    "red": "#f3c8c8",
    "off": "#e0e0e0",
}


class OperatorConsoleApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.backend = OperatorConsoleBackend()
        self.root.title("Operator Console")
        self.root.geometry("1720x980")

        self.last_log_render = ""
        self.last_output_render = ""
        self.log_process_var = tk.StringVar(value="spark_devices")
        self.preset_var = tk.StringVar()
        self.form_vars = {
            "dataset_id": tk.StringVar(),
            "robot_id": tk.StringVar(),
            "task_name": tk.StringVar(),
            "language_instruction": tk.StringVar(),
            "operator": tk.StringVar(value=os.environ.get("USER", "")),
            "active_arms": tk.StringVar(value="lightning"),
            "sensors_file": tk.StringVar(value="data_pipeline/configs/sensors.local.yaml"),
            "wrist_serial_no": tk.StringVar(),
            "scene_serial_no": tk.StringVar(),
            "gelsight_enabled": tk.BooleanVar(value=False),
            "gelsight_left_device_path": tk.StringVar(),
            "viewer_base_url": tk.StringVar(value="http://10.33.55.65:3000"),
            "notes": tk.StringVar(),
            "extra_topics": tk.StringVar(),
        }

        self.session_state_var = tk.StringVar(value="idle")
        self.validation_state_var = tk.StringVar(value="Validation: not_run")
        self.latest_episode_var = tk.StringVar(value="")
        self.latest_dataset_var = tk.StringVar(value="")
        self.latest_viewer_var = tk.StringVar(value="")
        self.command_var = tk.StringVar(value="")

        self.health_cards: dict[str, tuple[tk.Label, tk.Label, tk.Button, tk.Button]] = {}

        self._build_ui()
        self._load_first_preset()
        self._tick()

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=0)
        self.root.grid_columnconfigure(2, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.root)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
        header.grid_columnconfigure(1, weight=1)
        tk.Label(header, text="Operator Console", font=("Helvetica", 20, "bold")).grid(row=0, column=0, sticky="w")
        state_frame = tk.Frame(header)
        state_frame.grid(row=0, column=1, sticky="e")
        tk.Label(state_frame, textvariable=self.session_state_var, font=("Helvetica", 14)).pack(anchor="e")
        tk.Label(state_frame, textvariable=self.validation_state_var, font=("Helvetica", 11)).pack(anchor="e")

        left = tk.Frame(self.root)
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        center = tk.Frame(self.root)
        center.grid(row=1, column=1, sticky="nsew", padx=5, pady=(0, 10))
        right = tk.Frame(self.root)
        right.grid(row=1, column=2, sticky="nsew", padx=(5, 10), pady=(0, 10))
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_form(left)
        self._build_health(center)
        self._build_logs(right)

    def _build_form(self, parent: tk.Widget) -> None:
        form = tk.LabelFrame(parent, text="Session")
        form.pack(fill="both", expand=True)

        row = 0
        tk.Label(form, text="Preset").grid(row=row, column=0, sticky="w", padx=8, pady=4)
        preset_ids = [preset_id for preset_id, _ in self.backend.list_presets()]
        preset_menu = ttk.Combobox(form, textvariable=self.preset_var, values=preset_ids, state="readonly", width=42)
        preset_menu.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        preset_menu.bind("<<ComboboxSelected>>", lambda _event: self._apply_preset())

        entries = [
            ("Dataset ID", "dataset_id"),
            ("Robot ID", "robot_id"),
            ("Task Name", "task_name"),
            ("Language", "language_instruction"),
            ("Operator", "operator"),
            ("Active Arms", "active_arms"),
            ("Sensors File", "sensors_file"),
            ("Wrist Serial", "wrist_serial_no"),
            ("Scene Serial", "scene_serial_no"),
            ("GelSight Left Path", "gelsight_left_device_path"),
            ("Viewer Base URL", "viewer_base_url"),
            ("Notes", "notes"),
            ("Extra Topics", "extra_topics"),
        ]
        for label, key in entries:
            row += 1
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            values = ("lightning", "thunder", "lightning,thunder") if key == "active_arms" else None
            if values:
                widget = ttk.Combobox(form, textvariable=self.form_vars[key], values=values, state="readonly", width=42)
            else:
                widget = tk.Entry(form, textvariable=self.form_vars[key], width=46)
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=4)

        row += 1
        tk.Checkbutton(form, text="Enable GelSight", variable=self.form_vars["gelsight_enabled"]).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=4
        )

        row += 1
        buttons = tk.Frame(form)
        buttons.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=8)

        self.start_session_button = tk.Button(buttons, text="Start Session", command=self._start_session, width=16)
        self.start_session_button.grid(row=0, column=0, padx=3, pady=3)
        self.stop_session_button = tk.Button(buttons, text="Stop Session", command=self._stop_session, width=16)
        self.stop_session_button.grid(row=0, column=1, padx=3, pady=3)
        self.validate_button = tk.Button(buttons, text="Validate", command=self._validate, width=16)
        self.validate_button.grid(row=1, column=0, padx=3, pady=3)

        row += 1
        info = tk.LabelFrame(form, text="Latest Artifacts")
        info.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        tk.Label(info, text="Episode").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        tk.Label(info, textvariable=self.latest_episode_var, anchor="w", width=48).grid(row=0, column=1, sticky="w")
        tk.Label(info, text="Dataset").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        tk.Label(info, textvariable=self.latest_dataset_var, anchor="w", width=48).grid(row=1, column=1, sticky="w")
        tk.Label(info, text="Viewer").grid(row=2, column=0, sticky="w", padx=6, pady=3)
        tk.Label(info, textvariable=self.latest_viewer_var, anchor="w", width=48, wraplength=380, justify="left").grid(
            row=2, column=1, sticky="w"
        )

        form.grid_columnconfigure(1, weight=1)

    def _build_health(self, parent: tk.Widget) -> None:
        frame = tk.LabelFrame(parent, text="Subsystem Health")
        frame.pack(fill="both", expand=True)
        for row, name in enumerate(
            ["spark_devices", "teleop_gui", "realsense_contract", "gelsight_contract", "recorder", "converter"]
        ):
            card = tk.LabelFrame(frame, text=name.replace("_", " ").title())
            card.grid(row=row, column=0, sticky="ew", padx=8, pady=6)
            summary = tk.Label(card, text="Unknown", bg=STATUS_COLORS["off"], width=42, anchor="w", justify="left")
            summary.pack(fill="x", padx=6, pady=(6, 4))
            details = tk.Label(card, text="", anchor="w", justify="left", wraplength=360)
            details.pack(fill="x", padx=6, pady=(0, 6))
            controls = tk.Frame(card)
            controls.pack(fill="x", padx=6, pady=(0, 6))
            start_button = tk.Button(controls, text="Start", width=10, command=lambda process=name: self._start_named_process(process))
            start_button.pack(side="left", padx=(0, 6))
            stop_button = tk.Button(controls, text="Stop", width=10, command=lambda process=name: self._stop_named_process(process))
            stop_button.pack(side="left")
            self.health_cards[name] = (summary, details, start_button, stop_button)
        frame.grid_columnconfigure(0, weight=1)

    def _build_logs(self, parent: tk.Widget) -> None:
        command_frame = tk.LabelFrame(parent, text="Selected Process Command")
        command_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(command_frame, textvariable=self.command_var, anchor="w", justify="left", wraplength=760).pack(
            fill="x", padx=6, pady=6
        )

        logs_frame = tk.LabelFrame(parent, text="Process Logs")
        logs_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        ttk.Combobox(
            logs_frame,
            textvariable=self.log_process_var,
            values=list(self.backend.processes.keys()),
            state="readonly",
            width=24,
        ).pack(anchor="w", padx=6, pady=6)
        self.log_text = ScrolledText(logs_frame, wrap="word", height=22)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log_text.configure(state="disabled")

        output_frame = tk.LabelFrame(parent, text="Action Output")
        output_frame.grid(row=3, column=0, sticky="nsew")
        self.output_text = ScrolledText(output_frame, wrap="word", height=14)
        self.output_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.output_text.configure(state="disabled")

    def _load_first_preset(self) -> None:
        presets = self.backend.list_presets()
        if not presets:
            return
        self.preset_var.set(presets[0][0])
        self._apply_preset()

    def _apply_preset(self) -> None:
        preset_id = self.preset_var.get().strip()
        if not preset_id:
            return
        preset = self.backend.get_preset(preset_id)
        self.form_vars["dataset_id"].set(str(preset.get("dataset_id", "")))
        self.form_vars["robot_id"].set(str(preset.get("robot_id", "")))
        self.form_vars["task_name"].set(str(preset.get("task_name", "")))
        self.form_vars["language_instruction"].set(str(preset.get("language_instruction", "")))
        if preset.get("operator"):
            self.form_vars["operator"].set(str(preset.get("operator", "")))
        self.form_vars["active_arms"].set(str(preset.get("active_arms", "lightning")))
        self.form_vars["sensors_file"].set(str(preset.get("sensors_file", "data_pipeline/configs/sensors.local.yaml")))
        self.form_vars["wrist_serial_no"].set(str(preset.get("realsense", {}).get("wrist_serial_no", "")))
        self.form_vars["scene_serial_no"].set(str(preset.get("realsense", {}).get("scene_serial_no", "")))
        self.form_vars["gelsight_enabled"].set(bool(preset.get("gelsight", {}).get("enabled", False)))
        self.form_vars["gelsight_left_device_path"].set(str(preset.get("gelsight", {}).get("left_device_path", "")))
        self.form_vars["viewer_base_url"].set(str(preset.get("viewer_base_url", "")))
        self.form_vars["notes"].set("")
        self.form_vars["extra_topics"].set("")

    def _config(self) -> dict[str, object]:
        return {
            "preset_id": self.preset_var.get().strip(),
            "dataset_id": self.form_vars["dataset_id"].get().strip(),
            "robot_id": self.form_vars["robot_id"].get().strip(),
            "task_name": self.form_vars["task_name"].get().strip(),
            "language_instruction": self.form_vars["language_instruction"].get().strip(),
            "operator": self.form_vars["operator"].get().strip(),
            "active_arms": self.form_vars["active_arms"].get().strip(),
            "sensors_file": self.form_vars["sensors_file"].get().strip(),
            "wrist_serial_no": self.form_vars["wrist_serial_no"].get().strip(),
            "scene_serial_no": self.form_vars["scene_serial_no"].get().strip(),
            "realsense_enabled": True,
            "gelsight_enabled": bool(self.form_vars["gelsight_enabled"].get()),
            "gelsight_enable_left": bool(self.form_vars["gelsight_enabled"].get()),
            "gelsight_enable_right": False,
            "gelsight_left_device_path": self.form_vars["gelsight_left_device_path"].get().strip(),
            "gelsight_right_device_path": "",
            "viewer_base_url": self.form_vars["viewer_base_url"].get().strip(),
            "notes": self.form_vars["notes"].get().strip(),
            "extra_topics": self.form_vars["extra_topics"].get().strip(),
        }

    def _start_session(self) -> None:
        self.backend.start_session(self._config())

    def _stop_session(self) -> None:
        self.backend.stop_session()

    def _validate(self) -> None:
        self.backend.start_validation(self._config())

    def _start_recording(self) -> None:
        self.backend.start_recording(self._config())

    def _stop_recording(self) -> None:
        self.backend.stop_recording()

    def _convert_latest(self) -> None:
        self.backend.start_conversion(self._config())

    def _open_viewer(self) -> None:
        self.backend.open_viewer(self._config())

    def _start_named_process(self, name: str) -> None:
        self.backend.start_named_process(name, self._config())

    def _stop_named_process(self, name: str) -> None:
        self.backend.stop_named_process(name)

    def _tick(self) -> None:
        config = self._config()
        self.backend.request_health_refresh(config)
        snapshot = self.backend.snapshot(config)
        self.session_state_var.set(f"State: {snapshot['session_state']}")
        self.validation_state_var.set(f"Validation: {snapshot.get('validation_state', 'not_run')}")
        self.latest_episode_var.set(snapshot.get("latest_episode_id") or "")
        self.latest_dataset_var.set(snapshot.get("latest_dataset_id") or "")
        self.latest_viewer_var.set(snapshot.get("latest_viewer_url") or "")
        self._render_health(snapshot.get("health", {}))
        self._render_logs(snapshot)
        self._render_output(snapshot)
        self._update_button_states(snapshot)
        self.root.after(1000, self._tick)

    def _render_health(self, health: dict[str, dict[str, object]]) -> None:
        for name, widgets in self.health_cards.items():
            summary_widget, details_widget, _start_button, _stop_button = widgets
            card = health.get(name, {"status": "off", "summary": "Unknown", "details": []})
            status = str(card.get("status", "off"))
            summary_widget.configure(text=str(card.get("summary", "Unknown")), bg=STATUS_COLORS.get(status, "#e0e0e0"))
            details = card.get("details", [])
            details_widget.configure(text="\n".join(details) if details else "")

    def _render_logs(self, snapshot: dict[str, object]) -> None:
        selected = self.log_process_var.get().strip() or "spark_devices"
        logs = self.backend.get_process_logs(selected)
        rendered = "\n".join(logs[-200:])
        if rendered == self.last_log_render:
            process = snapshot.get("processes", {}).get(selected, {})
            self.command_var.set(str(process.get("command", "")))
            return
        self.last_log_render = rendered
        process = snapshot.get("processes", {}).get(selected, {})
        self.command_var.set(str(process.get("command", "")))
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert(tk.END, rendered)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _render_output(self, snapshot: dict[str, object]) -> None:
        lines = []
        lines.append(f"Session state: {snapshot.get('session_state', 'idle')}")
        lines.append(f"Validation state: {snapshot.get('validation_state', 'not_run')}")
        lines.append("")
        if snapshot.get("last_action_error"):
            lines.append("Last error:")
            lines.append(str(snapshot["last_action_error"]))
            lines.append("")
        if snapshot.get("last_validation_output"):
            lines.append("Validate output:")
            lines.append(str(snapshot["last_validation_output"]))
            lines.append("")
        if snapshot.get("latest_recording_check_output"):
            lines.append("Recording check:")
            lines.append(str(snapshot["latest_recording_check_output"]))
            lines.append("")
        if snapshot.get("latest_conversion_output"):
            lines.append("Convert output:")
            lines.append(str(snapshot["latest_conversion_output"]))
        rendered = "\n".join(lines).strip()
        if rendered == self.last_output_render:
            return
        self.last_output_render = rendered
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, rendered)
        self.output_text.see(tk.END)
        self.output_text.configure(state="disabled")

    def _update_button_states(self, snapshot: dict[str, object]) -> None:
        config = self._config()
        session_state = str(snapshot.get("session_state", "idle"))
        validation_state = str(snapshot.get("validation_state", "not_run"))
        ready = session_state in {"ready_for_dry_run", "ready_to_record", "recorded", "converted", "review_ready"}
        can_record = validation_state == "passed" and session_state in {"ready_to_record", "recorded", "converted", "review_ready"}
        processes = snapshot.get("processes", {})
        recorder_state = processes.get("recorder", {}).get("state")
        converter_state = processes.get("converter", {}).get("state")
        recording_ready = bool(snapshot.get("latest_episode_id")) and snapshot.get("latest_recording_ok") is True
        recording_check_running = bool(snapshot.get("recording_check_running"))
        viewer_available = self.backend.viewer_target_available(config)
        session_running = any(
            str(processes.get(name, {}).get("state", "stopped")) in {"running", "starting", "stopping", "failed"}
            for name in ("spark_devices", "teleop_gui", "realsense_contract", "gelsight_contract", "recorder", "converter")
        )

        self.start_session_button.configure(state="normal" if not session_running else "disabled")
        self.stop_session_button.configure(state="normal" if session_running else "disabled")
        self.validate_button.configure(
            state="normal" if (ready or session_state == "bringing_up") and validation_state != "running" else "disabled"
        )
        for name, widgets in self.health_cards.items():
            _summary_widget, _details_widget, start_button, stop_button = widgets
            state = str(processes.get(name, {}).get("state", "stopped"))
            start_enabled = state not in {"running", "starting", "stopping"}
            stop_enabled = state in {"running", "starting", "failed"}
            if name == "gelsight_contract" and not self.form_vars["gelsight_enabled"].get():
                start_enabled = False
                stop_enabled = False
            if name == "recorder":
                self._update_recorder_card_buttons(
                    start_button=start_button,
                    stop_button=stop_button,
                    recorder_state=str(recorder_state),
                    can_record=bool(can_record),
                    recording_check_running=recording_check_running,
                )
                continue
            if name == "converter":
                self._update_converter_card_buttons(
                    start_button=start_button,
                    stop_button=stop_button,
                    converter_state=str(converter_state),
                    recording_ready=recording_ready,
                    viewer_available=viewer_available,
                )
                continue
            start_button.configure(state="normal" if start_enabled else "disabled")
            stop_button.configure(state="normal" if stop_enabled else "disabled")

    def _update_recorder_card_buttons(
        self,
        *,
        start_button: tk.Button,
        stop_button: tk.Button,
        recorder_state: str,
        can_record: bool,
        recording_check_running: bool,
    ) -> None:
        if recorder_state == "running":
            start_button.configure(text="Record", command=self._start_recording, state="disabled")
            stop_button.configure(text="Stop", command=self._stop_recording, state="normal")
            return

        if recording_check_running:
            start_button.configure(text="Analyzing", command=self._start_recording, state="disabled")
            stop_button.configure(text="Wait", command=self._stop_recording, state="disabled")
            return

        start_button.configure(text="Record", command=self._start_recording, state="normal" if can_record else "disabled")
        stop_button.configure(text="Stop", command=self._stop_recording, state="disabled")

    def _update_converter_card_buttons(
        self,
        *,
        start_button: tk.Button,
        stop_button: tk.Button,
        converter_state: str,
        recording_ready: bool,
        viewer_available: bool,
    ) -> None:
        if converter_state == "running":
            start_button.configure(text="Convert", command=self._convert_latest, state="disabled")
            stop_button.configure(text="Stop", command=lambda: self._stop_named_process("converter"), state="normal")
            return

        if recording_ready:
            start_button.configure(text="Convert", command=self._convert_latest, state="normal")
            stop_button.configure(text="Open Viewer", command=self._open_viewer, state="normal" if viewer_available else "disabled")
            return

        if viewer_available:
            start_button.configure(text="Open Viewer", command=self._open_viewer, state="normal")
            stop_button.configure(text="Stop", command=lambda: self._stop_named_process("converter"), state="disabled")
            return

        start_button.configure(text="Convert", command=self._convert_latest, state="disabled")
        stop_button.configure(text="Stop", command=lambda: self._stop_named_process("converter"), state="disabled")


def main() -> int:
    root = tk.Tk()
    app = OperatorConsoleApp(root)
    try:
        root.mainloop()
    finally:
        app.backend.stop_session()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
