# Episode Manifest Design

## Purpose

`episode_manifest.json` is the raw episode's resolved snapshot.

It exists so one raw bag can still be understood later without depending on:

- current UI state
- current local sensors files
- current calibration files
- current code assumptions about what was probably recorded


## Core Decision

Each raw episode carries one manifest that answers:

- what this take was
- which session setup produced it
- which profile reference was active
- which sensors were actually resolved
- which topics were actually recorded
- which repo commit created it

Reusable policy stays outside the manifest. Episode-time truth stays inside it.


## Current Manifest Shape

Today the recorder writes these top-level sections:

- `episode`
- `session` when the take came from a resolved session-plan path
- `profile`
- `capture`
- `sensors`
- `recorded_topics`
- `provenance`

Example shape:

```json
{
  "episode": {
    "episode_id": "episode-20260406-190533",
    "task_name": "pick_place",
    "language_instruction": "pick up the object and place it in the target area",
    "active_arms": ["lightning"],
    "operator": "srinivas"
  },
  "session": {
    "session_id": "20260406-185500",
    "active_arms": ["lightning"],
    "sensors_file": "data_pipeline/configs/sensors.local.yaml",
    "devices": [...],
    "selected_topics": [...]
  },
  "profile": {
    "name": "multisensor_20hz",
    "clock_policy": "host_capture_time_v1"
  },
  "capture": {
    "start_time_ns": 1712448333000000000,
    "end_time_ns": 1712448341000000000,
    "storage": {
      "bag_storage_id": "mcap"
    }
  },
  "sensors": {
    "sensors_file": "data_pipeline/configs/sensors.local.yaml",
    "calibration_results_file": "data_pipeline/configs/calibration.local.json",
    "devices": [...]
  },
  "recorded_topics": [
    {
      "topic": "/spark/session/teleop_active",
      "message_type": "std_msgs/msg/Bool"
    }
  ],
  "provenance": {
    "git_commit": "<repo commit sha>"
  }
}
```

Notes:

- `session` is conditional
- `recorded_topics` is intentionally a flat list snapshot
- detailed per-sensor metadata lives under `sensors.devices`


## What Each Section Means

### `episode`

This is the human-facing description of the take:

- episode id
- task name
- language instruction
- active arms
- operator

This is the minimum answer to:

- what was this take supposed to be?

### `session`

This is the resolved session snapshot when the take came from the operator
console or another session-plan path.

It captures:

- resolved active arms
- chosen sensors file
- resolved devices
- resolved selected topics

This matters because the session plan is the concrete recording decision, not
just a UI blob.

### `profile`

This is the conversion-policy reference recorded at take time.

Today it stores only:

- profile name
- clock policy

The manifest does not inline the full reusable YAML.

### `capture`

This is the raw bag write metadata:

- start and end time
- bag storage backend

This is where the manifest says how the raw bag was written.

### `sensors`

This ties the take back to the local rig description at record time.

It records:

- the selected sensors file path
- the selected calibration results file path when present
- resolved device entries under `sensors.devices`

Those device entries are where the detailed sensor metadata lives.

### `recorded_topics`

This is the resolved topic inventory snapshot for the take.

It records only:

- topic name
- ROS message type

That is enough for readers that need to understand what the recorder actually
captured, without stuffing static topic-contract prose into every episode.

### `provenance`

This is where code-level provenance goes.

Current provenance includes:

- `provenance.git_commit`

That is the repository commit recorded at episode creation time.


## What Belongs In The Manifest

The manifest should carry episode-specific or record-time-resolved truth such
as:

- episode metadata
- resolved session metadata when recorded through the operator console
- the active profile reference
- capture storage details
- resolved sensor device entries
- recorded topic inventory
- record-time provenance

For sensors, that includes record-time metadata such as:

- serial numbers or device paths
- camera model and firmware when available
- stream profiles and intrinsics when exposed by the bridge
- calibration snapshot when solved calibration exists


## What Does Not Belong In The Manifest

The manifest should not become a dumping ground for reusable config or dead
version markers.

Keep these outside it:

- the shared topic contract
- the full reusable conversion YAML
- the live sensors file as a mutable source of truth
- the live calibration file as a mutable source of truth
- archive-time transcode results
- decorative schema or inventory version fields that no reader uses

The rule is simple:

- store resolved episode truth
- do not duplicate reusable policy
- do not add fields just because they sound future-proof


## Relationship To Other Files

### Sensors file

The sensors file maps physical device identity to canonical sensor keys.

It answers:

- which physical device is usually `/spark/cameras/world/scene_1`?

It does not answer the full per-episode question of what was actually recorded.

### Calibration results

`calibration.local.json` holds the current solved camera geometry.

It remains the working local results file, but the recorder snapshots the
relevant solved values into the manifest so old episodes stay self-describing.
