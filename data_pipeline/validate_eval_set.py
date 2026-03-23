#!/usr/bin/env python3

"""Run the minimal V1 eval set against dummy and optional real raw episodes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.convert_episode_bag_to_lerobot import main as convert_episode_main  # noqa: E402
from data_pipeline.generate_dummy_episode import main as generate_dummy_episode_main  # noqa: E402
from data_pipeline.pipeline_utils import (  # noqa: E402
    DEFAULT_PROFILE_PATH,
    manifest_dataset_id,
    manifest_episode_id,
    write_json,
)
from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dataset_snapshot(dataset_root: Path, dataset_id: str) -> dict[str, Any]:
    dataset = LeRobotDataset(repo_id=dataset_id, root=dataset_root, download_videos=False)
    try:
        return {
            "dataset_root": str(dataset_root),
            "total_episodes": dataset.meta.total_episodes,
            "total_frames": dataset.num_frames,
            "feature_keys": sorted(
                key for key in dataset.meta.features if not key.startswith("meta/")
            ),
        }
    finally:
        dataset.finalize()


def generate_dummy_episode(raw_root: Path, profile: str | Path) -> Path:
    episode_id = "eval-dummy-tactile"
    episode_dir = raw_root / episode_id
    if episode_dir.exists():
        shutil.rmtree(episode_dir)

    rc = generate_dummy_episode_main(
        [
            "--raw-root",
            str(raw_root),
            "--episode-id",
            episode_id,
            "--dataset-id",
            "eval_dummy_multisensor_v1",
            "--duration-s",
            "0.5",
            "--include-tactile",
            "--profile",
            str(profile),
        ]
    )
    if rc != 0:
        raise RuntimeError(f"Dummy episode generation failed with exit code {rc}")
    return episode_dir


def convert_episode(episode_dir: Path, published_root: Path, profile: str) -> dict[str, Any]:
    cmd = [
        str(episode_dir),
        "--published-root",
        str(published_root),
    ]
    if profile and profile != "auto":
        cmd.extend(["--profile", str(profile)])

    rc = convert_episode_main(cmd)
    if rc != 0:
        raise RuntimeError(f"Episode conversion failed with exit code {rc} for {episode_dir}")

    manifest = read_json(episode_dir / "episode_manifest.json")
    dataset_root = published_root / manifest_dataset_id(manifest)
    artifact_root = dataset_root / "meta" / "spark_conversion" / manifest_episode_id(manifest)
    return {
        "episode_id": manifest_episode_id(manifest),
        "dataset_id": manifest_dataset_id(manifest),
        "conversion_summary": read_json(artifact_root / "conversion_summary.json"),
        "dataset_snapshot": dataset_snapshot(dataset_root, manifest_dataset_id(manifest)),
        "artifact_root": str(artifact_root),
    }


def evaluate_episode(
    label: str,
    episode_dir: Path,
    published_root: Path,
    profile: str,
) -> dict[str, Any]:
    try:
        result = convert_episode(episode_dir, published_root, profile)
    except Exception as exc:  # noqa: BLE001
        return {
            "label": label,
            "episode_dir": str(episode_dir),
            "status": "fail",
            "error": str(exc),
        }

    return {
        "label": label,
        "episode_dir": str(episode_dir),
        "status": "pass",
        **result,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--work-root", type=Path, default=Path("/tmp/pipeline_eval"))
    parser.add_argument("--real-episode", type=Path, action="append", default=[])
    parser.add_argument("--skip-dummy", action="store_true")
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--clean", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    work_root = args.work_root.resolve()
    raw_root = work_root / "raw"
    published_root = work_root / "published"
    report_root = work_root / "reports"

    if args.clean and work_root.exists():
        shutil.rmtree(work_root)

    raw_root.mkdir(parents=True, exist_ok=True)
    published_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []

    if not args.skip_dummy:
        dummy_profile = args.profile if args.profile != "auto" else str(DEFAULT_PROFILE_PATH)
        dummy_episode_dir = generate_dummy_episode(raw_root, dummy_profile)
        entries.append(
            evaluate_episode(
                label="dummy",
                episode_dir=dummy_episode_dir,
                published_root=published_root,
                profile=str(dummy_profile),
            )
        )

    real_episode_paths = [path.resolve() for path in args.real_episode]
    for index, episode_dir in enumerate(real_episode_paths, start=1):
        entries.append(
            evaluate_episode(
                label=f"real_{index}",
                episode_dir=episode_dir,
                published_root=published_root,
                profile=str(args.profile),
            )
        )

    summary = {
        "profile": str(args.profile),
        "work_root": str(work_root),
        "dummy_included": not args.skip_dummy,
        "real_episode_count": len(real_episode_paths),
        "require_real": args.require_real,
        "entries": entries,
    }
    write_json(report_root / "evaluation_summary.json", summary)

    if args.require_real and not real_episode_paths:
        print("No real episode supplied while --require-real was set.")
        return 1

    failures = [entry for entry in entries if entry["status"] != "pass"]
    print(f"eval_report={report_root / 'evaluation_summary.json'}")
    print(f"entries={len(entries)} failures={len(failures)}")
    if failures:
        for entry in failures:
            print(f"FAIL {entry['label']}: {entry['error']}")
        return 1

    if not real_episode_paths:
        print("Real-episode eval not run; pass --real-episode <episode_dir> to include it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
