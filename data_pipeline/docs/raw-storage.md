# Raw Storage Contract

## Goal

Keep raw episode capture lossless while reducing bag size and removing the old `sqlite3` default.

## Decision

- Raw episode recording defaults to:
  - `storage_id: mcap`
  - `storage_preset_profile: zstd_fast`
- This compression is lossless.
- Published LeRobot export remains unchanged:
  - parquet for low-dimensional data
  - MP4 for RGB image fields

## Boundary

- This decision applies only to the raw bag under `raw_episodes/<episode_id>/bag/`.
- It does not change:
  - topic names
  - topic semantics
  - published dataset schema
  - depth publication policy

## Requirements

- `record_episode.py` must default to `mcap + zstd_fast`.
- Raw episode manifests must stamp:
  - `bag_storage_id`
  - `bag_storage_preset_profile`
- Conversion must auto-detect bag storage from `bag/metadata.yaml` and must not assume `sqlite3`.
- Recording integrity checks must continue to use `bag/metadata.yaml`, which is backend-agnostic.

## Non-Goals

- Do not invent a custom depth-in-MP4 export path.
- Do not change the published LeRobot RGB/state/action design in this step.
- Do not add lossy raw capture compression in this step.

## Follow-On Work

- Re-evaluate raw bag size after MCAP migration.
- If raw bags are still too large, tune:
  - depth rate
  - depth resolution
  - optional modality presets
- Treat published depth as a separate design decision, likely with a lossless sidecar format rather than RGB video export.
