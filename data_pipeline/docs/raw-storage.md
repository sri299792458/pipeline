# Raw Storage Contract

## Goal

Keep raw episode capture lossless while reducing bag size and removing the old `sqlite3` default.

## Decision

- Raw episode recording defaults to:
  - `storage_id: mcap`
  - `storage_preset_profile: zstd_fast`
- This compression is lossless.
- After recording completes successfully, the raw bag is trimmed to the first and last teleop command message activity with a small fixed pad:
  - basis: `/spark/<arm>/teleop/cmd_*`
  - policy: trim only head and tail idle time
  - default padding: `1.0 s` before and after
- Raw capture must also include the current shared teleop-activity signal:
  - basis: `/spark/session/teleop_active`
  - role: distinguish intentional pedal-off pauses from stale-action failures during published conversion
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
- It does not split episodes on mid-run gaps in command activity.
- It does not trim mid-episode pedal-off gaps out of the raw bag.

## Requirements

- `record_episode.py` must default to `mcap + zstd_fast`.
- Raw episode manifests must stamp:
  - `bag_storage_id`
  - `bag_storage_preset_profile`
- Raw episode manifests must stamp the applied trim policy and outcome under `raw_trim`.
- Conversion must auto-detect bag storage from `bag/metadata.yaml` and must not assume `sqlite3`.
- Recording integrity checks must continue to use `bag/metadata.yaml`, which is backend-agnostic.
- If teleop command topics are missing entirely, automatic raw trimming must skip rather than guess.
- New recordings must include the teleop-activity topic declared by the profile, even though published conversion may still fall back gracefully for older raw episodes that predate this signal.

## Non-Goals

- Do not invent a custom depth-in-MP4 export path.
- Do not change the published LeRobot RGB/state/action design in this step.
- Do not add lossy raw capture compression in this step.
- Do not gate live recording start/stop directly on foot-pedal state.

## Follow-On Work

- Re-evaluate raw bag size after MCAP migration.
- If raw bags are still too large after head/tail trimming, tune:
  - depth rate
  - depth resolution
  - optional modality presets
- Published depth is specified separately in [depth-storage.md](./depth-storage.md).
