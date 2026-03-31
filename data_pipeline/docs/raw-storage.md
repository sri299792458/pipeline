# Raw Storage Contract

## Goal

Keep raw episode capture lossless and low-overhead while removing the old
`sqlite3` default.

## Decision

- Raw episode recording defaults to:
  - `storage_id: mcap`
- The capture bag should be plain `mcap`, with no live bag-level compression
  preset by default.
- The capture bag should remain untrimmed.
- The capture bag should not be rewritten in place after recording completes.
- Head/tail trim moves to the offline archive step:
  - basis: `/spark/<arm>/teleop/cmd_*`
  - with `/spark/session/teleop_active`
  - policy: trim only head and tail idle time
  - default padding: `1.0 s` before and after
- Raw capture must also include the current shared teleop-activity signal:
  - basis: `/spark/session/teleop_active`
  - role: distinguish intentional pedal-off pauses from stale-action failures during published conversion
- Published LeRobot export remains unchanged:
  - parquet for low-dimensional data
  - MP4 for RGB image fields

## Boundary

- This decision applies to the preserved capture bag under
  `raw_episodes/<episode_id>/bag/`.
- It does not change:
  - topic names
  - topic semantics
  - published dataset schema
  - depth publication policy
- It does not split episodes on mid-run gaps in command activity.
- It does not trim mid-episode pedal-off gaps out of the archive bag.

## Requirements

- `record_episode.py` must default to plain `mcap`.
- Raw episode manifests must stamp:
  - `bag_storage_id`
- `bag_storage_preset_profile` should be `null` / unset by default for capture bags
- Raw episode manifests must not embed archive-specific trim/compression
  results.
- Conversion must auto-detect bag storage from `bag/metadata.yaml` and must not assume `sqlite3`.
- Recording integrity checks must continue to use `bag/metadata.yaml`, which is backend-agnostic.
- New recordings must include the teleop-activity topic declared by the profile, even though published conversion may still fall back gracefully for older raw episodes that predate this signal.
- Archive-time trim/compression provenance belongs in a separate archive manifest,
  not in the capture manifest.

## Non-Goals

- Do not invent a custom depth-in-MP4 export path.
- Do not change the published LeRobot RGB/state/action design in this step.
- Do not add lossy raw capture compression in this step.
- Do not gate live recording start/stop directly on foot-pedal state.
- Do not mutate the capture bag to make it smaller during recording.

## Follow-On Work

- Implement the offline archive step described in [archive-bag.md](./archive-bag.md).
- Re-evaluate raw capture size after switching to plain MCAP.
- If capture bags are still too large for short-term retention, tune:
  - depth rate
  - depth resolution
  - optional modality presets
- Published depth is specified separately in [depth-storage.md](./depth-storage.md).
