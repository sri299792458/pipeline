#!/usr/bin/python3

"""Record one raw V1 episode into a bag plus manifest."""

from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import rosbag2_py

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

DEFAULT_COMMAND_TRIM_PAD_BEFORE_S = 1.0
DEFAULT_COMMAND_TRIM_PAD_AFTER_S = 1.0


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
    parser.add_argument("--disable-command-trim", action="store_true")
    parser.add_argument("--command-trim-pad-before-s", type=float, default=DEFAULT_COMMAND_TRIM_PAD_BEFORE_S)
    parser.add_argument("--command-trim-pad-after-s", type=float, default=DEFAULT_COMMAND_TRIM_PAD_AFTER_S)
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


def bag_dir_size_bytes(bag_dir: Path) -> int:
    return sum(path.stat().st_size for path in bag_dir.rglob("*") if path.is_file())


def build_command_activity_topics(profile: dict, active_arms: list[str]) -> list[str]:
    action_sources = profile.get("published", {}).get("action", {}).get("sources", {})
    topics: list[str] = []
    for arm in active_arms:
        arm_sources = action_sources.get(arm, {})
        topics.extend(topic for topic in arm_sources.values() if topic)
    return sorted(set(topics))


def trim_bag_to_command_activity(
    bag_dir: Path,
    command_topics: list[str],
    storage_id: str,
    storage_preset_profile: str,
    pad_before_s: float,
    pad_after_s: float,
) -> dict[str, object]:
    trim_result: dict[str, object] = {
        "policy": "teleop_command_head_tail_v1",
        "activity_topics": command_topics,
        "pad_before_s": float(pad_before_s),
        "pad_after_s": float(pad_after_s),
        "status": "disabled",
        "applied": False,
    }
    if not command_topics:
        trim_result["status"] = "skipped_no_command_topics"
        return trim_result

    pad_before_ns = int(round(max(0.0, pad_before_s) * 1_000_000_000.0))
    pad_after_ns = int(round(max(0.0, pad_after_s) * 1_000_000_000.0))
    original_size_bytes = bag_dir_size_bytes(bag_dir)

    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    topics_and_types = reader.get_all_topics_and_types()
    topic_names = {topic.name for topic in topics_and_types}
    available_command_topics = [topic for topic in command_topics if topic in topic_names]
    trim_result["activity_topics"] = available_command_topics
    if not available_command_topics:
        trim_result["status"] = "skipped_topics_not_in_bag"
        return trim_result

    bag_start_ns: int | None = None
    bag_end_ns: int | None = None
    activity_start_ns: int | None = None
    activity_end_ns: int | None = None
    original_message_count = 0

    while reader.has_next():
        topic, _, bag_timestamp_ns = reader.read_next()
        original_message_count += 1
        if bag_start_ns is None:
            bag_start_ns = bag_timestamp_ns
        bag_end_ns = bag_timestamp_ns
        if topic in available_command_topics:
            if activity_start_ns is None:
                activity_start_ns = bag_timestamp_ns
            activity_end_ns = bag_timestamp_ns

    del reader

    trim_result["messages_before"] = original_message_count
    trim_result["size_bytes_before"] = original_size_bytes
    trim_result["bag_start_ns"] = bag_start_ns
    trim_result["bag_end_ns"] = bag_end_ns
    trim_result["activity_start_ns"] = activity_start_ns
    trim_result["activity_end_ns"] = activity_end_ns

    if bag_start_ns is None or bag_end_ns is None:
        trim_result["status"] = "skipped_empty_bag"
        return trim_result
    if activity_start_ns is None or activity_end_ns is None:
        trim_result["status"] = "skipped_no_command_activity"
        return trim_result

    trim_start_ns = max(bag_start_ns, activity_start_ns - pad_before_ns)
    trim_end_ns = min(bag_end_ns, activity_end_ns + pad_after_ns)
    trim_result["trim_start_ns"] = trim_start_ns
    trim_result["trim_end_ns"] = trim_end_ns

    if trim_start_ns <= bag_start_ns and trim_end_ns >= bag_end_ns:
        trim_result["status"] = "skipped_full_span"
        return trim_result

    temp_bag_dir = bag_dir.parent / f"{bag_dir.name}.trim_tmp"
    if temp_bag_dir.exists():
        shutil.rmtree(temp_bag_dir)

    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)

    writer_storage_options = rosbag2_py.StorageOptions(
        uri=str(temp_bag_dir),
        storage_id=storage_id,
        storage_preset_profile=(storage_preset_profile if storage_id == "mcap" else ""),
    )
    writer = rosbag2_py.SequentialWriter()
    writer.open(writer_storage_options, converter_options)

    for topic_id, topic_metadata in enumerate(topics_and_types):
        writer.create_topic(
            rosbag2_py.TopicMetadata(
                id=topic_id,
                name=topic_metadata.name,
                type=topic_metadata.type,
                serialization_format=topic_metadata.serialization_format,
            )
        )

    trimmed_message_count = 0
    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        if bag_timestamp_ns < trim_start_ns or bag_timestamp_ns > trim_end_ns:
            continue
        writer.write(topic, data, bag_timestamp_ns)
        trimmed_message_count += 1

    del writer
    del reader
    time.sleep(0.1)

    if trimmed_message_count == 0:
        shutil.rmtree(temp_bag_dir, ignore_errors=True)
        trim_result["status"] = "skipped_zero_messages_after_trim"
        return trim_result

    original_bag_dir = bag_dir.parent / f"{bag_dir.name}.pre_trim_backup"
    if original_bag_dir.exists():
        shutil.rmtree(original_bag_dir)
    bag_dir.rename(original_bag_dir)
    temp_bag_dir.rename(bag_dir)
    shutil.rmtree(original_bag_dir)

    trim_result["status"] = "applied"
    trim_result["applied"] = True
    trim_result["messages_after"] = trimmed_message_count
    trim_result["size_bytes_after"] = bag_dir_size_bytes(bag_dir)
    return trim_result


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
        if not args.disable_command_trim:
            command_topics = build_command_activity_topics(profile, active_arms)
            print("raw_trim_policy=teleop_command_head_tail_v1")
            print(f"raw_trim_activity_topics={','.join(command_topics)}")
            print(f"raw_trim_pad_before_s={args.command_trim_pad_before_s}")
            print(f"raw_trim_pad_after_s={args.command_trim_pad_after_s}")
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
    if not args.disable_command_trim and return_code == 0:
        command_topics = build_command_activity_topics(profile, active_arms)
        final_manifest["raw_trim"] = trim_bag_to_command_activity(
            bag_dir=bag_dir,
            command_topics=command_topics,
            storage_id=args.storage_id,
            storage_preset_profile=args.storage_preset_profile,
            pad_before_s=args.command_trim_pad_before_s,
            pad_after_s=args.command_trim_pad_after_s,
        )
    else:
        final_manifest["raw_trim"] = {
            "policy": "teleop_command_head_tail_v1",
            "activity_topics": build_command_activity_topics(profile, active_arms),
            "pad_before_s": float(args.command_trim_pad_before_s),
            "pad_after_s": float(args.command_trim_pad_after_s),
            "status": "disabled" if args.disable_command_trim else "skipped_nonzero_exit_code",
            "applied": False,
        }
    write_json(manifest_path, final_manifest)

    print(f"Finished episode {args.episode_id} with ros2 bag exit code {return_code}")
    raw_trim = final_manifest["raw_trim"]
    print(f"Raw trim status: {raw_trim['status']}")
    if raw_trim.get("applied"):
        print(
            "Trimmed bag size: "
            f"{raw_trim.get('size_bytes_before')} -> {raw_trim.get('size_bytes_after')} bytes"
        )
    print(f"Manifest: {manifest_path}")
    print(f"Notes: {notes_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
