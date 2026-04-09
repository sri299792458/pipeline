#!/usr/bin/python3

"""Create an offline archive bag from a preserved raw capture bag."""

from __future__ import annotations

import argparse
import heapq
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rosbag2_py
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import (  # noqa: E402
    DEFAULT_RAW_EPISODES_DIR,
    detect_bag_storage_id,
    read_bag_metadata,
    write_json,
)
from data_pipeline.archive_verification import (  # noqa: E402
    ArchiveImageTopicPair,
    verify_archive_structure,
)


IMAGE_TOPIC_TYPE = "sensor_msgs/msg/Image"
TELEOP_ACTIVITY_TOPIC = "/spark/session/teleop_active"
COMMAND_TOPIC_PATTERN = re.compile(r"^/spark/(lightning|thunder)/teleop/cmd_")
DEFAULT_TRIM_PAD_BEFORE_S = 1.0
DEFAULT_TRIM_PAD_AFTER_S = 1.0
DEFAULT_ARCHIVE_DIRNAME = "archive"
DEFAULT_ARCHIVE_ZSTD_PRESET = "zstd_small"
DEFAULT_PLAYBACK_START_DELAY_S = 5.0
POST_PLAYBACK_DRAIN_S = 2.0
ARCHIVE_DEPTH_MAX_M = 65.535


@dataclass(frozen=True)
class ImageTopicPlan:
    source_topic: str
    source_type: str
    modality: str
    out_transport: str
    intermediate_topic: str
    output_topic: str
    node_name: str


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[Any]
    log_path: Path
    log_handle: Any


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", help="Episode id, raw episode directory, or capture bag directory.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_EPISODES_DIR))
    parser.add_argument("--archive-dir-name", default=DEFAULT_ARCHIVE_DIRNAME)
    parser.add_argument("--trim-pad-before-s", type=float, default=DEFAULT_TRIM_PAD_BEFORE_S)
    parser.add_argument("--trim-pad-after-s", type=float, default=DEFAULT_TRIM_PAD_AFTER_S)
    parser.add_argument(
        "--archive-zstd-preset",
        default=DEFAULT_ARCHIVE_ZSTD_PRESET,
        choices=("zstd_fast", "zstd_small"),
        help="Final MCAP zstd preset for the archive bag.",
    )
    parser.add_argument("--playback-rate", type=float, default=1.0)
    parser.add_argument(
        "--playback-start-delay-s",
        type=float,
        default=DEFAULT_PLAYBACK_START_DELAY_S,
        help="Delay before rosbag playback starts, to allow discovery/subscriptions to settle.",
    )
    parser.add_argument("--domain-id", type=int, default=-1, help="ROS_DOMAIN_ID override for the offline transcode job.")
    parser.add_argument("--force", action="store_true", help="Overwrite any existing archive output for this episode.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary archive work directory after success.")
    return parser


def resolve_episode_dir(episode_ref: str, raw_root: Path) -> Path:
    candidate = Path(str(episode_ref)).expanduser()
    if candidate.is_dir():
        if (candidate / "bag").is_dir():
            return candidate.resolve()
        if (candidate / "metadata.yaml").is_file():
            return candidate.parent.resolve()
    if candidate.exists():
        raise RuntimeError(f"Unsupported episode reference: {candidate}")

    episode_dir = raw_root / str(episode_ref).strip()
    if (episode_dir / "bag").is_dir():
        return episode_dir.resolve()
    raise FileNotFoundError(f"Raw episode not found: {episode_ref}")


def relpath_or_abs(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def bag_dir_size_bytes(bag_dir: Path) -> int:
    return sum(path.stat().st_size for path in bag_dir.rglob("*") if path.is_file())


def metadata_sha256(bag_dir: Path) -> str | None:
    metadata_path = bag_dir / "metadata.yaml"
    if not metadata_path.is_file():
        return None
    digest = hashlib.sha256()
    with metadata_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def extract_message_timestamp_ns(msg: Any, bag_timestamp_ns: int) -> int:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return bag_timestamp_ns
    sec = int(getattr(stamp, "sec", 0))
    nanosec = int(getattr(stamp, "nanosec", 0))
    if sec == 0 and nanosec == 0:
        return bag_timestamp_ns
    return sec * 1_000_000_000 + nanosec


def list_topic_metadata(bag_dir: Path, storage_id: str) -> list[Any]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)
    return list(reader.get_all_topics_and_types())


def verify_capture_bag(bag_dir: Path, storage_id: str) -> dict[str, Any]:
    metadata = read_bag_metadata(bag_dir)
    topics = list_topic_metadata(bag_dir, storage_id)
    if not topics:
        raise RuntimeError(f"Capture bag has no topics: {bag_dir}")
    bag_info = metadata.get("rosbag2_bagfile_information", {})
    return {
        "status": "ok",
        "storage_id": storage_id,
        "topic_count": len(topics),
        "topics": sorted(topic.name for topic in topics),
        "message_count": int(bag_info.get("message_count", 0)),
        "duration_ns": int(bag_info.get("duration", {}).get("nanoseconds", 0)),
    }


def compute_trim_window(
    bag_dir: Path,
    storage_id: str,
    *,
    pad_before_s: float,
    pad_after_s: float,
) -> dict[str, Any]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    command_topics = sorted(topic for topic in topic_types if COMMAND_TOPIC_PATTERN.match(topic))
    has_teleop_activity = TELEOP_ACTIVITY_TOPIC in topic_types

    result: dict[str, Any] = {
        "policy": "teleop_command_and_activity_head_tail_v1",
        "command_topics": command_topics,
        "teleop_active_topic": TELEOP_ACTIVITY_TOPIC if has_teleop_activity else None,
        "pad_before_s": float(pad_before_s),
        "pad_after_s": float(pad_after_s),
        "status": "unknown",
        "applied": False,
    }

    bag_start_ns: int | None = None
    bag_end_ns: int | None = None
    activity_start_ns: int | None = None
    activity_end_ns: int | None = None
    original_message_count = 0

    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        original_message_count += 1
        if bag_start_ns is None:
            bag_start_ns = int(bag_timestamp_ns)
        bag_end_ns = int(bag_timestamp_ns)

        if topic in command_topics:
            if activity_start_ns is None:
                activity_start_ns = int(bag_timestamp_ns)
            activity_end_ns = int(bag_timestamp_ns)
            continue

        if topic == TELEOP_ACTIVITY_TOPIC:
            msg = deserialize_message(data, Bool)
            if bool(msg.data):
                if activity_start_ns is None:
                    activity_start_ns = int(bag_timestamp_ns)
                activity_end_ns = int(bag_timestamp_ns)

    result["messages_before"] = original_message_count
    result["bag_start_ns"] = bag_start_ns
    result["bag_end_ns"] = bag_end_ns
    result["activity_start_ns"] = activity_start_ns
    result["activity_end_ns"] = activity_end_ns
    result["size_bytes_before"] = bag_dir_size_bytes(bag_dir)

    if bag_start_ns is None or bag_end_ns is None:
        result["status"] = "skipped_empty_bag"
        return result
    if activity_start_ns is None or activity_end_ns is None:
        result["status"] = "skipped_no_activity"
        return result

    pad_before_ns = int(round(max(0.0, pad_before_s) * 1_000_000_000.0))
    pad_after_ns = int(round(max(0.0, pad_after_s) * 1_000_000_000.0))
    trim_start_ns = max(bag_start_ns, activity_start_ns - pad_before_ns)
    trim_end_ns = min(bag_end_ns, activity_end_ns + pad_after_ns)
    result["trim_start_ns"] = trim_start_ns
    result["trim_end_ns"] = trim_end_ns

    if trim_start_ns <= bag_start_ns and trim_end_ns >= bag_end_ns:
        result["status"] = "skipped_full_span"
        return result

    result["status"] = "ready"
    return result


def copy_bag(
    input_bag_dir: Path,
    output_bag_dir: Path,
    *,
    input_storage_id: str,
    output_storage_id: str,
    output_storage_preset_profile: str = "",
    trim_start_ns: int | None = None,
    trim_end_ns: int | None = None,
    topic_name_remap: dict[str, str] | None = None,
) -> dict[str, Any]:
    if output_bag_dir.exists():
        shutil.rmtree(output_bag_dir)

    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(input_bag_dir), storage_id=input_storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)
    topics_and_types = list(reader.get_all_topics_and_types())

    writer_storage_options = rosbag2_py.StorageOptions(
        uri=str(output_bag_dir),
        storage_id=output_storage_id,
        storage_preset_profile=output_storage_preset_profile if output_storage_id == "mcap" else "",
    )
    writer = rosbag2_py.SequentialWriter()
    writer.open(writer_storage_options, converter_options)

    for topic_id, topic_metadata in enumerate(topics_and_types):
        writer.create_topic(
            rosbag2_py.TopicMetadata(
                id=topic_id,
                name=(topic_name_remap or {}).get(topic_metadata.name, topic_metadata.name),
                type=topic_metadata.type,
                serialization_format=topic_metadata.serialization_format,
            )
        )

    message_count = 0
    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        bag_timestamp_ns = int(bag_timestamp_ns)
        if trim_start_ns is not None and bag_timestamp_ns < trim_start_ns:
            continue
        if trim_end_ns is not None and bag_timestamp_ns > trim_end_ns:
            continue
        writer.write((topic_name_remap or {}).get(topic, topic), data, bag_timestamp_ns)
        message_count += 1

    del writer
    del reader
    return {
        "message_count": message_count,
        "size_bytes": bag_dir_size_bytes(output_bag_dir),
    }


def merge_bags_to_archive(
    passthrough_bag_dir: Path,
    passthrough_storage_id: str,
    passthrough_topics: list[str],
    compressed_bag_dir: Path,
    compressed_storage_id: str,
    compressed_topic_name_remap: dict[str, str],
    output_bag_dir: Path,
    *,
    output_storage_preset_profile: str,
) -> dict[str, Any]:
    if output_bag_dir.exists():
        shutil.rmtree(output_bag_dir)

    passthrough_reader = rosbag2_py.SequentialReader()
    passthrough_reader.open(
        rosbag2_py.StorageOptions(uri=str(passthrough_bag_dir), storage_id=passthrough_storage_id),
        rosbag2_py.ConverterOptions("", ""),
    )
    compressed_reader = rosbag2_py.SequentialReader()
    compressed_reader.open(
        rosbag2_py.StorageOptions(uri=str(compressed_bag_dir), storage_id=compressed_storage_id),
        rosbag2_py.ConverterOptions("", ""),
    )

    passthrough_topic_set = set(passthrough_topics)
    compressed_topic_set = set(compressed_topic_name_remap)

    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(
            uri=str(output_bag_dir),
            storage_id="mcap",
            storage_preset_profile=output_storage_preset_profile,
        ),
        rosbag2_py.ConverterOptions("", ""),
    )

    created_topics: dict[str, str] = {}
    topic_id = 0
    for topic_metadata in passthrough_reader.get_all_topics_and_types():
        if topic_metadata.name not in passthrough_topic_set:
            continue
        created_topics[topic_metadata.name] = topic_metadata.type
        writer.create_topic(
            rosbag2_py.TopicMetadata(
                id=topic_id,
                name=topic_metadata.name,
                type=topic_metadata.type,
                serialization_format=topic_metadata.serialization_format,
            )
        )
        topic_id += 1

    for topic_metadata in compressed_reader.get_all_topics_and_types():
        if topic_metadata.name not in compressed_topic_set:
            continue
        output_name = compressed_topic_name_remap[topic_metadata.name]
        created_topics[output_name] = topic_metadata.type
        writer.create_topic(
            rosbag2_py.TopicMetadata(
                id=topic_id,
                name=output_name,
                type=topic_metadata.type,
                serialization_format=topic_metadata.serialization_format,
            )
        )
        topic_id += 1

    compressed_msg_type = CompressedImage
    sequence_index = 0
    heap: list[tuple[int, int, str, str, bytes]] = []

    def push_next(reader: rosbag2_py.SequentialReader, source_name: str) -> None:
        nonlocal sequence_index
        include_topics = passthrough_topic_set if source_name == "passthrough" else compressed_topic_set
        while reader.has_next():
            topic, data, bag_timestamp_ns = reader.read_next()
            if topic not in include_topics:
                continue
            bag_timestamp_ns = int(bag_timestamp_ns)
            if source_name == "compressed":
                msg = deserialize_message(data, compressed_msg_type)
                timestamp_ns = extract_message_timestamp_ns(msg, bag_timestamp_ns)
                final_topic = compressed_topic_name_remap[topic]
            else:
                timestamp_ns = bag_timestamp_ns
                final_topic = topic
            heapq.heappush(heap, (timestamp_ns, sequence_index, source_name, final_topic, data))
            sequence_index += 1
            return

    push_next(passthrough_reader, "passthrough")
    push_next(compressed_reader, "compressed")

    message_count = 0
    while heap:
        timestamp_ns, _, source_name, final_topic, data = heapq.heappop(heap)
        writer.write(final_topic, data, int(timestamp_ns))
        message_count += 1
        if source_name == "passthrough":
            push_next(passthrough_reader, "passthrough")
        else:
            push_next(compressed_reader, "compressed")

    del writer
    del passthrough_reader
    del compressed_reader
    return {
        "message_count": message_count,
        "size_bytes": bag_dir_size_bytes(output_bag_dir),
    }


def classify_image_topic(topic_name: str, topic_type: str) -> str | None:
    if topic_type != IMAGE_TOPIC_TYPE:
        return None
    if "/depth/" in topic_name:
        return "depth"
    return "rgb"


def build_archive_topic_plan(topic_metadata: list[Any]) -> tuple[list[str], list[ImageTopicPlan]]:
    passthrough_topics: list[str] = []
    image_plans: list[ImageTopicPlan] = []

    for index, topic in enumerate(sorted(topic_metadata, key=lambda item: item.name)):
        modality = classify_image_topic(topic.name, topic.type)
        if modality is None:
            passthrough_topics.append(topic.name)
            continue
        if modality == "depth":
            image_plans.append(
                ImageTopicPlan(
                    source_topic=topic.name,
                    source_type=topic.type,
                    modality="depth",
                    out_transport="compressedDepth",
                    intermediate_topic=f"/archive_depth_{index}/out/compressedDepth",
                    output_topic=f"{topic.name}/compressedDepth",
                    node_name=f"archive_depth_{index}",
                )
            )
        else:
            image_plans.append(
                ImageTopicPlan(
                    source_topic=topic.name,
                    source_type=topic.type,
                    modality="rgb",
                    out_transport="compressed",
                    intermediate_topic=f"/archive_rgb_{index}/out/compressed",
                    output_topic=f"{topic.name}/compressed",
                    node_name=f"archive_rgb_{index}",
                )
            )
    return passthrough_topics, image_plans


def check_required_transports() -> list[str]:
    ros2 = shutil.which("ros2")
    if ros2 is None:
        raise RuntimeError("Could not find `ros2` in PATH. Run from a ROS-sourced shell.")
    completed = subprocess.run(
        [ros2, "run", "image_transport", "list_transports"],
        check=True,
        capture_output=True,
        text=True,
    )
    transports = sorted(
        line.strip().split("/")[-1]
        for line in completed.stdout.splitlines()
        if line.strip().startswith("image_transport/")
    )
    required = {"raw", "compressed", "compressedDepth"}
    missing = sorted(required.difference(transports))
    if missing:
        raise RuntimeError(
            "Missing required image transports: "
            f"{missing}. Install `ros-jazzy-image-transport-plugins`."
        )
    return transports


def build_process_env(domain_id: int) -> dict[str, str]:
    env = os.environ.copy()
    env["ROS_DOMAIN_ID"] = str(domain_id)
    env.setdefault("ROS_LOCALHOST_ONLY", "1")
    return env


def spawn_logged_process(name: str, cmd: list[str], *, env: dict[str, str], log_path: Path) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
        preexec_fn=os.setsid,
    )
    return ManagedProcess(name=name, process=process, log_path=log_path, log_handle=handle)


def stop_managed_process(managed: ManagedProcess, *, timeout_s: float = 10.0) -> int:
    process = managed.process
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            deadline = time.time() + timeout_s
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            deadline = time.time() + 5.0
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            deadline = time.time() + 2.0
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
        return int(process.wait())
    finally:
        managed.log_handle.close()


def ensure_processes_alive(processes: list[ManagedProcess]) -> None:
    failed = [managed for managed in processes if managed.process.poll() not in (None,)]
    if not failed:
        return
    details = ", ".join(f"{managed.name} (log: {managed.log_path})" for managed in failed)
    raise RuntimeError(f"One or more archive helper processes exited early: {details}")


def choose_domain_id(requested: int) -> int:
    if requested >= 0:
        return requested
    return random.randint(120, 220)


def write_republisher_params_file(plan: ImageTopicPlan, logs_dir: Path) -> Path | None:
    if plan.modality == "rgb":
        params_text = (
            f"/{plan.node_name}/{plan.node_name}:\n"
            "  ros__parameters:\n"
            '    ".out.compressed.format": png\n'
            '    ".out.format": png\n'
        )
    elif plan.modality == "depth":
        params_text = (
            f"/{plan.node_name}/{plan.node_name}:\n"
            "  ros__parameters:\n"
            f'    ".out.compressedDepth.depth_max": {ARCHIVE_DEPTH_MAX_M}\n'
            '    ".out.compressedDepth.format": png\n'
            f'    ".out.depth_max": {ARCHIVE_DEPTH_MAX_M}\n'
            '    ".out.format": png\n'
        )
    else:
        return None

    params_path = logs_dir / f"{plan.node_name}.params.yaml"
    params_path.write_text(params_text, encoding="utf-8")
    return params_path


def run_image_transport_transcode(
    source_bag_dir: Path,
    source_storage_id: str,
    *,
    output_bag_dir: Path,
    image_plans: list[ImageTopicPlan],
    playback_rate: float,
    playback_start_delay_s: float,
    domain_id: int,
    logs_dir: Path,
) -> dict[str, Any]:
    if output_bag_dir.exists():
        shutil.rmtree(output_bag_dir)

    env = build_process_env(domain_id)
    ros2 = shutil.which("ros2")
    if ros2 is None:
        raise RuntimeError("Could not find `ros2` in PATH. Run from a ROS-sourced shell.")

    processes: list[ManagedProcess] = []
    try:
        for plan in image_plans:
            params_path = write_republisher_params_file(plan, logs_dir)
            cmd = [
                ros2,
                "run",
                "image_transport",
                "republish",
                "--ros-args",
                "-r",
                f"__node:={plan.node_name}",
                "-r",
                f"__ns:=/{plan.node_name}",
                "-p",
                "in_transport:=raw",
                "-p",
                f"out_transport:={plan.out_transport}",
                "-r",
                f"in:={plan.source_topic}",
            ]
            if params_path is not None:
                cmd.extend(["--params-file", str(params_path)])
            processes.append(
                spawn_logged_process(
                    plan.node_name,
                    cmd,
                    env=env,
                    log_path=logs_dir / f"{plan.node_name}.log",
                )
            )

        time.sleep(1.0)
        ensure_processes_alive(processes)

        record_topics = [plan.intermediate_topic for plan in image_plans]
        recorder_cmd = [
            ros2,
            "bag",
            "record",
            "--output",
            str(output_bag_dir),
            "--storage",
            "mcap",
            "--storage-preset-profile",
            "none",
            "--disable-keyboard-controls",
            "--include-unpublished-topics",
            "--topics",
            *record_topics,
        ]
        recorder = spawn_logged_process(
            "archive_recorder",
            recorder_cmd,
            env=env,
            log_path=logs_dir / "archive_recorder.log",
        )
        processes.append(recorder)

        time.sleep(1.0)
        ensure_processes_alive(processes)

        player_cmd = [
            ros2,
            "bag",
            "play",
            "--input",
            str(source_bag_dir),
            source_storage_id,
            "--read-ahead-queue-size",
            "1000",
            "--disable-keyboard-controls",
            "--delay",
            str(playback_start_delay_s),
            "--rate",
            str(playback_rate),
        ]
        player = spawn_logged_process(
            "archive_player",
            player_cmd,
            env=env,
            log_path=logs_dir / "archive_player.log",
        )
        player_exit_code = int(player.process.wait())
        player.log_handle.close()
        if player_exit_code != 0:
            raise RuntimeError(f"ros2 bag play failed with exit code {player_exit_code}. See {player.log_path}")

        time.sleep(POST_PLAYBACK_DRAIN_S)
        ensure_processes_alive(processes)

        recorder_exit_code = stop_managed_process(recorder)
        if recorder_exit_code != 0:
            raise RuntimeError(f"ros2 bag record failed with exit code {recorder_exit_code}. See {recorder.log_path}")

        stats = {
            "domain_id": domain_id,
            "republished_topics": [plan.output_topic for plan in image_plans],
            "plain_archive_message_count": int(
                read_bag_metadata(output_bag_dir)["rosbag2_bagfile_information"].get("message_count", 0)
            ),
            "plain_archive_size_bytes": bag_dir_size_bytes(output_bag_dir),
            "logs_dir": relpath_or_abs(logs_dir),
        }
        return stats
    finally:
        for managed in processes:
            if managed.name == "archive_recorder":
                continue
            if managed.process.poll() is None:
                stop_managed_process(managed)
            else:
                managed.log_handle.close()


def load_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.playback_rate <= 0.0:
        raise RuntimeError("--playback-rate must be > 0")

    raw_root = Path(args.raw_root).expanduser().resolve()
    episode_dir = resolve_episode_dir(args.episode, raw_root)
    capture_bag_dir = episode_dir / "bag"
    if not capture_bag_dir.is_dir():
        raise FileNotFoundError(f"Capture bag directory not found: {capture_bag_dir}")

    archive_dir = episode_dir / args.archive_dir_name
    archive_manifest_path = archive_dir / "archive_manifest.json"
    archive_bag_dir = archive_dir / "bag"
    work_dir = archive_dir / ".work"
    logs_dir = archive_dir / "logs"

    if archive_dir.exists():
        if not args.force:
            raise RuntimeError(f"Archive output already exists: {archive_dir}. Use --force to overwrite.")
        shutil.rmtree(archive_dir)

    archive_dir.mkdir(parents=True, exist_ok=False)
    work_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    episode_manifest = load_json_if_present(episode_dir / "episode_manifest.json")
    capture_storage_id = detect_bag_storage_id(capture_bag_dir)
    capture_size_bytes = bag_dir_size_bytes(capture_bag_dir)
    archive_manifest: dict[str, Any] = {
        "archive_created_ns": time.time_ns(),
        "tool": {
            "script": "data_pipeline/archive_episode.py",
            "git_commit": git_revision(),
        },
        "source_capture_bag": {
            "episode_dir": relpath_or_abs(episode_dir),
            "bag_dir": relpath_or_abs(capture_bag_dir),
            "storage_id": capture_storage_id,
            "size_bytes": capture_size_bytes,
            "metadata_sha256": metadata_sha256(capture_bag_dir),
            "verified": None,
            "verification": None,
        },
        "episode_manifest_path": relpath_or_abs(episode_dir / "episode_manifest.json")
        if (episode_dir / "episode_manifest.json").is_file()
        else None,
        "trim": None,
        "image_transcode": None,
        "archive_storage": {
            "storage_id": "mcap",
            "storage_preset_profile": args.archive_zstd_preset,
        },
        "archive_output": {
            "archive_dir": relpath_or_abs(archive_dir),
            "bag_dir": relpath_or_abs(archive_bag_dir),
            "size_bytes": None,
            "message_count": None,
            "verified": None,
            "verification": None,
        },
        "capture_bag_retention": {
            "state": "retained",
            "deleted_at_ns": None,
        },
    }
    write_json(archive_manifest_path, archive_manifest)

    verification = verify_capture_bag(capture_bag_dir, capture_storage_id)
    archive_manifest["source_capture_bag"]["verified"] = True
    archive_manifest["source_capture_bag"]["verification"] = verification
    write_json(archive_manifest_path, archive_manifest)

    trim_result = compute_trim_window(
        capture_bag_dir,
        capture_storage_id,
        pad_before_s=args.trim_pad_before_s,
        pad_after_s=args.trim_pad_after_s,
    )
    playback_source_bag_dir = capture_bag_dir
    playback_storage_id = capture_storage_id

    if trim_result["status"] == "ready":
        trimmed_bag_dir = work_dir / "trimmed_capture"
        trimmed_stats = copy_bag(
            capture_bag_dir,
            trimmed_bag_dir,
            input_storage_id=capture_storage_id,
            output_storage_id=capture_storage_id,
            trim_start_ns=int(trim_result["trim_start_ns"]),
            trim_end_ns=int(trim_result["trim_end_ns"]),
        )
        trim_result["status"] = "applied"
        trim_result["applied"] = True
        trim_result["trimmed_bag_dir"] = relpath_or_abs(trimmed_bag_dir)
        trim_result["messages_after"] = trimmed_stats["message_count"]
        trim_result["size_bytes_after"] = trimmed_stats["size_bytes"]
        playback_source_bag_dir = trimmed_bag_dir
    else:
        trim_result["applied"] = False
        trim_result["messages_after"] = trim_result.get("messages_before")
        trim_result["size_bytes_after"] = trim_result.get("size_bytes_before")

    archive_manifest["trim"] = trim_result
    write_json(archive_manifest_path, archive_manifest)

    topic_metadata = list_topic_metadata(playback_source_bag_dir, playback_storage_id)
    passthrough_topics, image_plans = build_archive_topic_plan(topic_metadata)
    available_transports = check_required_transports()

    plain_archive_bag_dir = work_dir / "plain_archive_bag"
    transcode_stats = run_image_transport_transcode(
        playback_source_bag_dir,
        playback_storage_id,
        output_bag_dir=plain_archive_bag_dir,
        image_plans=image_plans,
        playback_rate=float(args.playback_rate),
        playback_start_delay_s=float(args.playback_start_delay_s),
        domain_id=choose_domain_id(args.domain_id),
        logs_dir=logs_dir,
    )
    archive_manifest["image_transcode"] = {
        "available_transports": available_transports,
        "rgb_policy": "compressed/png",
        "depth_policy": "compressedDepth/png",
        "source_topic_count": len(image_plans),
        "source_topics": [
            {
                "source_topic": plan.source_topic,
                "modality": plan.modality,
                "intermediate_topic": plan.intermediate_topic,
                "archive_topic": plan.output_topic,
                "out_transport": plan.out_transport,
            }
            for plan in image_plans
        ],
        "passthrough_topic_count": len(passthrough_topics),
        "plain_archive_bag_dir": relpath_or_abs(plain_archive_bag_dir),
        "plain_archive_message_count": transcode_stats["plain_archive_message_count"],
        "plain_archive_size_bytes": transcode_stats["plain_archive_size_bytes"],
        "transcode_domain_id": transcode_stats["domain_id"],
        "logs_dir": transcode_stats["logs_dir"],
    }
    write_json(archive_manifest_path, archive_manifest)

    final_copy_stats = merge_bags_to_archive(
        playback_source_bag_dir,
        playback_storage_id,
        passthrough_topics,
        plain_archive_bag_dir,
        "mcap",
        {plan.intermediate_topic: plan.output_topic for plan in image_plans},
        archive_bag_dir,
        output_storage_preset_profile=args.archive_zstd_preset,
    )
    archive_manifest["archive_output"]["size_bytes"] = final_copy_stats["size_bytes"]
    archive_manifest["archive_output"]["message_count"] = final_copy_stats["message_count"]
    archive_manifest["archive_output"]["verification"] = verify_archive_structure(
        playback_source_bag_dir,
        playback_storage_id,
        archive_bag_dir,
        "mcap",
        passthrough_topics,
        [
            ArchiveImageTopicPair(
                source_topic=plan.source_topic,
                archive_topic=plan.output_topic,
                modality=plan.modality,
            )
            for plan in image_plans
        ],
    )
    archive_manifest["archive_output"]["verified"] = (
        archive_manifest["archive_output"]["verification"]["status"] == "ok"
    )
    if not archive_manifest["archive_output"]["verified"]:
        write_json(archive_manifest_path, archive_manifest)
        raise RuntimeError(
            "Lightweight archive verification failed: "
            f"{archive_manifest['archive_output']['verification']['errors']}"
        )
    write_json(archive_manifest_path, archive_manifest)

    if not args.keep_temp:
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"Archive created for {episode_dir.name}")
    print(f"Capture bag: {capture_bag_dir}")
    print(f"Archive bag: {archive_bag_dir}")
    print(f"Archive manifest: {archive_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
