#!/usr/bin/python3

"""Record one raw V2 episode into a bag plus manifest."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import (
    DEFAULT_BAG_STORAGE_ID,
    DEFAULT_BAG_STORAGE_PRESET_PROFILE,
    DEFAULT_RAW_EPISODES_DIR,
    build_notes_template,
    build_recorded_topics_snapshot,
    collect_candidate_topics,
    effective_profile_for_session,
    get_git_commit,
    infer_sensor_metadata,
    list_live_topics,
    load_optional_calibration_results,
    load_optional_sensor_overrides,
    MANIFEST_SCHEMA_VERSION,
    make_episode_id,
    normalize_active_arms,
    now_ns,
    parse_task_list,
    profile_compatibility_entry,
    required_topics_from_profile,
    resolve_profile_for_active_arms,
    write_json,
)

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--language-instruction", default="")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_EPISODES_DIR))
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--storage-id", default=DEFAULT_BAG_STORAGE_ID)
    parser.add_argument("--storage-preset-profile", default=DEFAULT_BAG_STORAGE_PRESET_PROFILE)
    parser.add_argument("--sensors-file", default=None)
    parser.add_argument("--calibration-file", default="")
    parser.add_argument("--session-plan-file", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extra-topics", default="")
    parser.add_argument("--active-arms", required=True)
    return parser


def select_topics(profile: dict, live_topics: dict[str, str], extra_topics: list[str]) -> tuple[list[str], list[str]]:
    candidate_topics = collect_candidate_topics(profile)
    required_topics = required_topics_from_profile(profile)
    selected = [topic for topic in candidate_topics if topic in live_topics]

    missing_required = [topic for topic in required_topics if topic not in live_topics]
    if missing_required:
        raise RuntimeError(f"Missing required topics: {missing_required}")

    for topic in extra_topics:
        if topic in live_topics and topic not in selected:
            selected.append(topic)

    return sorted(selected), missing_required


def select_topics_from_session_plan(
    session_capture_plan: dict,
    live_topics: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    selected_topics = [
        str(topic).strip()
        for topic in session_capture_plan.get("selected_topics", [])
        if str(topic).strip()
    ]
    if not selected_topics:
        raise RuntimeError("Session capture plan does not define any selected_topics.")

    plan_extra_topics = [
        str(topic).strip()
        for topic in session_capture_plan.get("selected_extra_topics", [])
        if str(topic).strip()
    ]
    missing_topics = [topic for topic in selected_topics if topic not in live_topics]
    if missing_topics:
        raise RuntimeError(f"Session plan topics are not live: {missing_topics}")
    return sorted(dict.fromkeys(selected_topics)), missing_topics, sorted(dict.fromkeys(plan_extra_topics))


def build_manifest(
    args: argparse.Namespace,
    profile: dict,
    profile_path: Path,
    active_arms: list[str],
    selected_topics: list[str],
    live_topics: dict[str, str],
    sensor_overrides: dict[str, dict],
    sensors_file: Path | None,
    calibration_results: dict[str, object],
    calibration_results_path: Path | None,
    start_time_ns: int,
    end_time_ns: int,
    session_capture_plan: dict | None,
) -> dict:
    sensors = infer_sensor_metadata(
        selected_topics,
        sensor_overrides=sensor_overrides,
        calibration_results=calibration_results,
        calibration_results_path=calibration_results_path,
    )
    recorded_topics = build_recorded_topics_snapshot(
        selected_topics=selected_topics,
        live_topics=live_topics,
        sensors=sensors,
    )
    profile_relpath = str(profile_path.relative_to(REPO_ROOT)) if profile_path.is_relative_to(REPO_ROOT) else str(profile_path)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "episode": {
            "episode_id": args.episode_id,
            "task_name": args.task_name,
            "language_instruction": str(args.language_instruction).strip() or None,
            "active_arms": active_arms,
            "operator": args.operator,
        },
    }
    if session_capture_plan is not None:
        manifest["session"] = session_capture_plan
    manifest.update(
        {
            "profile": {
                "name": profile["profile_name"],
                "version": profile["profile_version"],
                "path": profile_relpath,
                "clock_policy": profile["dataset"]["clock_policy"],
            },
            "capture": {
                "start_time_ns": start_time_ns,
                "end_time_ns": end_time_ns,
                "storage": {
                    "bag_storage_id": args.storage_id,
                    "bag_storage_preset_profile": (
                        args.storage_preset_profile if args.storage_id == "mcap" and args.storage_preset_profile else None
                    ),
                },
                "record_exit_code": None,
            },
            "sensors": {
                "inventory_version": 2,
                "sensors_file": str(sensors_file.relative_to(REPO_ROOT)) if sensors_file and sensors_file.is_relative_to(REPO_ROOT) else (str(sensors_file) if sensors_file else None),
                "calibration_results_file": (
                    str(calibration_results_path.relative_to(REPO_ROOT))
                    if calibration_results_path and calibration_results_path.is_relative_to(REPO_ROOT)
                    else (str(calibration_results_path) if calibration_results_path else None)
                ),
                "devices": sensors,
            },
            "recorded_topics": recorded_topics,
            "provenance": {
                "git_commit": get_git_commit(),
            },
        }
    )
    return manifest


def load_optional_json(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"Session plan file not found: {json_path}")
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {json_path}, got {type(data).__name__}")
    return data


def ensure_episode_dir(raw_root: Path, episode_id: str) -> Path:
    episode_dir = raw_root / episode_id
    episode_dir.mkdir(parents=True, exist_ok=False)
    return episode_dir


def run_recorder(
    bag_dir: Path,
    topics: list[str],
    storage_id: str,
    storage_preset_profile: str,
) -> int:
    cmd = ["ros2", "bag", "record", "--output", str(bag_dir), "--storage", storage_id]
    if storage_id == "mcap" and storage_preset_profile:
        cmd.extend(["--storage-preset-profile", storage_preset_profile])
    cmd.extend(topics)
    process = subprocess.Popen(cmd, preexec_fn=os.setsid)
    try:
        return process.wait()
    except KeyboardInterrupt:
        os.killpg(process.pid, signal.SIGINT)
        return process.wait()


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    raw_root = Path(args.raw_root)
    args.episode_id = args.episode_id or make_episode_id()
    sensors_file = Path(args.sensors_file).expanduser().resolve() if args.sensors_file else None
    sensor_overrides = load_optional_sensor_overrides(sensors_file)
    calibration_results, calibration_results_path = load_optional_calibration_results(args.calibration_file)
    session_capture_plan = load_optional_json(args.session_plan_file)
    extra_topics = parse_task_list(args.extra_topics)

    live_topics = list_live_topics()
    active_arms = normalize_active_arms(parse_task_list(args.active_arms))
    if session_capture_plan is not None:
        plan_active_arms = normalize_active_arms(session_capture_plan.get("active_arms", active_arms))
        if plan_active_arms != active_arms:
            raise RuntimeError(
                f"Session plan active arms {plan_active_arms} do not match requested active arms {active_arms}"
            )
    profile, resolved_profile_path = resolve_profile_for_active_arms(args.profile, active_arms)
    if session_capture_plan is not None:
        selected_topics, _, extra_topics = select_topics_from_session_plan(session_capture_plan, live_topics)
        enabled_sensor_keys = [
            str(device.get("sensor_key", "")).strip()
            for device in session_capture_plan.get("devices", [])
            if isinstance(device, dict) and bool(device.get("enabled", False))
        ]
        effective_profile = effective_profile_for_session(profile, active_arms, enabled_sensor_keys)
        compatibility = profile_compatibility_entry(
            profile=effective_profile,
            profile_path=resolved_profile_path,
            active_arms=active_arms,
            selected_topics=selected_topics,
        )
        if not compatibility["compatible"]:
            raise RuntimeError(
                f"Session plan is not compatible with profile {compatibility['name']}: {compatibility['reasons']}"
            )
    else:
        effective_profile = effective_profile_for_session(profile, active_arms, [])
        selected_topics, _ = select_topics(effective_profile, live_topics, extra_topics)

    if args.dry_run:
        dry_run_manifest = build_manifest(
            args=args,
            profile=profile,
            profile_path=resolved_profile_path,
            active_arms=active_arms,
            selected_topics=selected_topics,
            live_topics=live_topics,
            sensor_overrides=sensor_overrides,
            sensors_file=sensors_file,
            calibration_results=calibration_results,
            calibration_results_path=calibration_results_path,
            start_time_ns=0,
            end_time_ns=0,
            session_capture_plan=session_capture_plan,
        )
        print(f"episode_id={args.episode_id}")
        print(f"active_arms={','.join(active_arms)}")
        print(f"profile_name={profile['profile_name']}")
        print(f"profile_path={resolved_profile_path}")
        print(f"bag_storage_id={args.storage_id}")
        if args.storage_id == "mcap" and args.storage_preset_profile:
            print(f"bag_storage_preset_profile={args.storage_preset_profile}")
        print(f"language_instruction={dry_run_manifest['episode'].get('language_instruction') or ''}")
        print(f"bag_topics={len(selected_topics)}")
        for sensor in dry_run_manifest["sensors"]["devices"]:
            print(
                "sensor="
                f"key={sensor.get('sensor_key')} "
                f"serial={sensor.get('serial_number')} "
                f"modality={sensor.get('modality')} "
                f"topics={len(sensor.get('topic_names', []))}"
            )
        for topic in selected_topics:
            print(f"{topic} [{live_topics[topic]}]")
        return 0

    episode_dir = ensure_episode_dir(raw_root, args.episode_id)
    manifest_path = episode_dir / "episode_manifest.json"
    notes_path = episode_dir / "notes.md"
    bag_dir = episode_dir / "bag"

    start_time_ns = now_ns()
    manifest = build_manifest(
        args=args,
        profile=profile,
        profile_path=resolved_profile_path,
        active_arms=active_arms,
        selected_topics=selected_topics,
        live_topics=live_topics,
        sensor_overrides=sensor_overrides,
        sensors_file=sensors_file,
        calibration_results=calibration_results,
        calibration_results_path=calibration_results_path,
        start_time_ns=start_time_ns,
        end_time_ns=start_time_ns,
        session_capture_plan=session_capture_plan,
    )

    notes_body = build_notes_template(manifest)
    if args.notes:
        notes_body += "\n" + args.notes.strip() + "\n"
    notes_path.write_text(notes_body, encoding="utf-8")
    write_json(manifest_path, manifest)

    print(f"Recording episode {args.episode_id} into {episode_dir}")
    print(
        "Raw bag storage: "
        f"{args.storage_id}"
        + (
            f" ({args.storage_preset_profile})"
            if args.storage_id == "mcap" and args.storage_preset_profile
            else ""
        )
    )
    print("Topics:")
    for topic in selected_topics:
        print(f"  {topic} [{live_topics[topic]}]")
    print("Press Ctrl+C to stop recording.")

    return_code = run_recorder(bag_dir, selected_topics, args.storage_id, args.storage_preset_profile)
    end_time_ns = now_ns()

    final_manifest = build_manifest(
        args=args,
        profile=profile,
        profile_path=resolved_profile_path,
        active_arms=active_arms,
        selected_topics=selected_topics,
        live_topics=live_topics,
        sensor_overrides=sensor_overrides,
        sensors_file=sensors_file,
        calibration_results=calibration_results,
        calibration_results_path=calibration_results_path,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
        session_capture_plan=session_capture_plan,
    )
    final_manifest["capture"]["record_exit_code"] = return_code
    write_json(manifest_path, final_manifest)

    print(f"Finished episode {args.episode_id} with ros2 bag exit code {return_code}")
    print(f"Manifest: {manifest_path}")
    print(f"Notes: {notes_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
