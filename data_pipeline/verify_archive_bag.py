#!/usr/bin/python3

"""Verify one archive bag against its capture bag."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.archive_episode import copy_bag  # noqa: E402
from data_pipeline.archive_episode import resolve_episode_dir  # noqa: E402
from data_pipeline.archive_verification import (  # noqa: E402
    ArchiveImageTopicPair,
    verify_archive_payload_roundtrip,
    verify_archive_structure,
)
from data_pipeline.pipeline_utils import DEFAULT_RAW_EPISODES_DIR  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", help="Episode id or raw episode directory.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_EPISODES_DIR))
    parser.add_argument("--archive-dir-name", default="archive")
    parser.add_argument(
        "--full-payload",
        action="store_true",
        help="Run exact decoded image round-trip verification in addition to lightweight structural checks.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the verification result as JSON.",
    )
    return parser


def load_archive_context(episode_dir: Path, archive_dir_name: str) -> tuple[Path, dict[str, Any], list[str], list[ArchiveImageTopicPair]]:
    archive_dir = episode_dir / archive_dir_name
    archive_manifest_path = archive_dir / "archive_manifest.json"
    archive_bag_dir = archive_dir / "bag"
    if not archive_manifest_path.is_file():
        raise FileNotFoundError(f"Archive manifest not found: {archive_manifest_path}")
    if not archive_bag_dir.is_dir():
        raise FileNotFoundError(f"Archive bag directory not found: {archive_bag_dir}")

    archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
    image_transcode = archive_manifest.get("image_transcode") or {}
    image_pairs = [
        ArchiveImageTopicPair(
            source_topic=entry["source_topic"],
            archive_topic=entry["archive_topic"],
            modality=entry["modality"],
        )
        for entry in image_transcode.get("source_topics", [])
    ]
    source_image_topics = {pair.source_topic for pair in image_pairs}
    passthrough_topics = []
    verification_topics = (archive_manifest.get("source_capture_bag") or {}).get("verification", {}).get("topics", [])
    for topic in verification_topics:
        if topic not in source_image_topics:
            passthrough_topics.append(topic)

    return archive_bag_dir, archive_manifest, passthrough_topics, image_pairs


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    raw_root = Path(args.raw_root).expanduser().resolve()
    episode_dir = resolve_episode_dir(args.episode, raw_root)
    capture_bag_dir = episode_dir / "bag"
    if not capture_bag_dir.is_dir():
        raise FileNotFoundError(f"Capture bag directory not found: {capture_bag_dir}")

    archive_bag_dir, archive_manifest, passthrough_topics, image_pairs = load_archive_context(
        episode_dir,
        args.archive_dir_name,
    )

    source_storage_id = str((archive_manifest.get("source_capture_bag") or {}).get("storage_id") or "mcap")
    archive_storage_id = str((archive_manifest.get("archive_storage") or {}).get("storage_id") or "mcap")
    trim_info = archive_manifest.get("trim") or {}
    playback_source_bag_dir = capture_bag_dir
    temporary_trim_root: tempfile.TemporaryDirectory[str] | None = None
    if trim_info.get("applied"):
        trimmed_bag_dir = Path(str(trim_info.get("trimmed_bag_dir", "")))
        if not trimmed_bag_dir.is_absolute():
            trimmed_bag_dir = (REPO_ROOT / trimmed_bag_dir).resolve()
        if trimmed_bag_dir.is_dir():
            playback_source_bag_dir = trimmed_bag_dir
        else:
            temporary_trim_root = tempfile.TemporaryDirectory(prefix="archive_verify_trim_")
            playback_source_bag_dir = Path(temporary_trim_root.name) / "trimmed_capture"
            copy_bag(
                capture_bag_dir,
                playback_source_bag_dir,
                input_storage_id=source_storage_id,
                output_storage_id=source_storage_id,
                trim_start_ns=int(trim_info["trim_start_ns"]),
                trim_end_ns=int(trim_info["trim_end_ns"]),
            )

    try:
        result: dict[str, Any] = {
            "episode_dir": str(episode_dir),
            "capture_bag_dir": str(capture_bag_dir),
            "playback_source_bag_dir": str(playback_source_bag_dir),
            "archive_bag_dir": str(archive_bag_dir),
            "lightweight": verify_archive_structure(
                playback_source_bag_dir,
                source_storage_id,
                archive_bag_dir,
                archive_storage_id,
                passthrough_topics,
                image_pairs,
            ),
            "full_payload": None,
        }

        if args.full_payload:
            result["full_payload"] = verify_archive_payload_roundtrip(
                playback_source_bag_dir,
                source_storage_id,
                archive_bag_dir,
                archive_storage_id,
                image_pairs,
            )

        lightweight_ok = result["lightweight"]["status"] == "ok"
        full_ok = result["full_payload"] is None or result["full_payload"]["status"] == "ok"
        overall_ok = lightweight_ok and full_ok

        if args.print_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Episode: {episode_dir.name}")
            print(f"Lightweight verification: {result['lightweight']['status']}")
            if args.full_payload:
                print(f"Full payload verification: {result['full_payload']['status']}")
            if not overall_ok:
                for section in ("lightweight", "full_payload"):
                    payload = result.get(section)
                    if not payload:
                        continue
                    for error in payload.get("errors", []):
                        print(f"{section}: {error}")

        return 0 if overall_ok else 1
    finally:
        if temporary_trim_root is not None:
            temporary_trim_root.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
