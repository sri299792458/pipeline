#!/usr/bin/python3

"""Record one raw V1 episode into a bag plus manifest."""

from __future__ import annotations

import argparse
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
    collect_candidate_topics,
    get_git_commit,
    infer_sensor_metadata,
    list_live_topics,
    load_optional_sensor_overrides,
    make_episode_id,
    normalize_active_arms,
    now_ns,
    parse_task_list,
    required_topics_from_profile,
    resolve_profile_for_active_arms,
    write_json,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--language-instruction", default="")
    parser.add_argument("--robot-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_EPISODES_DIR))
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--storage-id", default=DEFAULT_BAG_STORAGE_ID)
    parser.add_argument("--storage-preset-profile", default=DEFAULT_BAG_STORAGE_PRESET_PROFILE)
    parser.add_argument("--sensors-file", default=None)
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


def build_manifest(
    args: argparse.Namespace,
    profile: dict,
    active_arms: list[str],
    selected_topics: list[str],
    live_topics: dict[str, str],
    sensor_overrides: dict[str, dict],
    start_time_ns: int,
    end_time_ns: int,
) -> dict:
    profile_name = profile["profile_name"]
    profile_version = profile["profile_version"]
    topic_types = {topic: live_topics[topic] for topic in selected_topics}
    sensors = infer_sensor_metadata(selected_topics, sensor_overrides=sensor_overrides)

    return {
        "episode_id": args.episode_id,
        "dataset_id": args.dataset_id,
        "task_name": args.task_name,
        "language_instruction": str(args.language_instruction).strip() or None,
        "robot_id": args.robot_id,
        "active_arms": active_arms,
        "operator": args.operator,
        "start_time_ns": start_time_ns,
        "end_time_ns": end_time_ns,
        "topics": selected_topics,
        "topic_types": topic_types,
        "sensor_inventory_version": 2,
        "sensors": sensors,
        "mapping_profile": profile_name,
        "profile_version": profile_version,
        "clock_policy": profile["dataset"]["clock_policy"],
        "bag_storage_id": args.storage_id,
        "bag_storage_preset_profile": (
            args.storage_preset_profile if args.storage_id == "mcap" and args.storage_preset_profile else None
        ),
        "git_commit": get_git_commit(),
    }


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
    sensor_overrides = load_optional_sensor_overrides(args.sensors_file)
    extra_topics = parse_task_list(args.extra_topics)

    live_topics = list_live_topics()
    active_arms = normalize_active_arms(parse_task_list(args.active_arms))
    profile, resolved_profile_path = resolve_profile_for_active_arms(args.profile, active_arms)
    selected_topics, _ = select_topics(profile, live_topics, extra_topics)

    if args.dry_run:
        dry_run_manifest = build_manifest(
            args=args,
            profile=profile,
            active_arms=active_arms,
            selected_topics=selected_topics,
            live_topics=live_topics,
            sensor_overrides=sensor_overrides,
            start_time_ns=0,
            end_time_ns=0,
        )
        print(f"episode_id={args.episode_id}")
        print(f"active_arms={','.join(active_arms)}")
        print(f"mapping_profile={profile['profile_name']}")
        print(f"profile_path={resolved_profile_path}")
        print(f"bag_storage_id={args.storage_id}")
        if args.storage_id == "mcap" and args.storage_preset_profile:
            print(f"bag_storage_preset_profile={args.storage_preset_profile}")
        print(f"language_instruction={dry_run_manifest['language_instruction'] or ''}")
        print(f"bag_topics={len(selected_topics)}")
        for sensor in dry_run_manifest["sensors"]:
            print(
                "sensor="
                f"id={sensor.get('sensor_id')} "
                f"serial={sensor.get('serial_number')} "
                f"modality={sensor.get('modality')} "
                f"attached_to={sensor.get('attached_to')} "
                f"mount_site={sensor.get('mount_site')}"
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
        active_arms=active_arms,
        selected_topics=selected_topics,
        live_topics=live_topics,
        sensor_overrides=sensor_overrides,
        start_time_ns=start_time_ns,
        end_time_ns=start_time_ns,
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
        active_arms=active_arms,
        selected_topics=selected_topics,
        live_topics=live_topics,
        sensor_overrides=sensor_overrides,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
    )
    final_manifest["record_exit_code"] = return_code
    write_json(manifest_path, final_manifest)

    print(f"Finished episode {args.episode_id} with ros2 bag exit code {return_code}")
    print(f"Manifest: {manifest_path}")
    print(f"Notes: {notes_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
