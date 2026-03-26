# Session Profile V2

## Purpose

This document defines the session-level object used by the operator console and raw recorder.

V2 keeps only three concepts here:

- the shared topic contract
- the local sensors file
- one resolved session profile

Everything else that had grown around this, such as overlay labels, expected-device lists,
and profile-compatibility matrices, is intentionally out of the main workflow.


## Ground Rules

### Discovery is truth

If a device is not discovered, it is not part of the live session.

### The sensors file provides defaults, not fake devices

The sensors file may tell the system:

- which serial or device path usually maps to which canonical role
- optional local metadata for that role
- optional geometry or calibration references

It does not create live devices.

### One session has one fixed setup

At session start, the operator chooses:

- session metadata
- which discovered devices are recorded
- which canonical role each recorded device uses

All episodes in that session inherit the same setup.

### Operators confirm intent, not topic meaning

Operators may change:

- whether a discovered device is recorded
- which allowed canonical role a discovered device uses

Operators do not redefine:

- canonical role names
- topic names
- timestamp semantics


## Core Objects

### Shared contract

The shared contract defines:

- canonical V2 topic names
- canonical role names
- timestamp meanings
- dataset-facing semantics

See [topic-contract.md](./topic-contract.md).

### Sensors file

The sensors file is the one local rig file.

Its main job is:

- serial or device-path to canonical-role mapping

It may also carry optional metadata such as:

- display labels
- sensor ids
- mount information
- calibration references

Solved camera geometry is a separate local file, not something the operator should type into the session profile.

### Session profile

The session profile is the resolved session truth.

It contains:

- `session_id`
- `active_arms`
- `sensors_file`
- resolved `devices`
- resolved `selected_topics`

The operator may save a resolved session profile for later reuse.

Saved session profiles are:

- user-local
- convenience defaults
- not part of the shared contract

The built-in `init` profile is only the checked-in starting point.


## Canonical Role Vocabulary

The first V2 vocabulary is:

- arms
  - `lightning`
  - `thunder`
- wrist cameras
  - `lightning_wrist_1`
  - `thunder_wrist_1`
- scene cameras
  - `scene_1`
  - `scene_2`
  - `scene_3`
- tactile sensors
  - `lightning_finger_left`
  - `lightning_finger_right`
  - `thunder_finger_left`
  - `thunder_finger_right`

Role choices are constrained by device kind:

- `realsense` may use only wrist or scene roles
- `gelsight` may use only finger roles


## Session Profile Shape

Example:

```json
{
  "schema_version": 4,
  "contract_version": "v2",
  "session_id": "20260323-101500",
  "active_arms": ["lightning"],
  "sensors_file": "data_pipeline/configs/sensors.local.yaml",
  "devices": [
    {
      "kind": "realsense",
      "identifier": "130322273305",
      "serial_number": "130322273305",
      "model": "Intel RealSense D405",
      "role": "lightning_wrist_1",
      "enabled": true
    },
    {
      "kind": "realsense",
      "identifier": "213622251272",
      "serial_number": "213622251272",
      "model": "Intel RealSense D455",
      "role": "scene_1",
      "enabled": true
    }
  ],
  "selected_topics": [
    "/spark/lightning/robot/joint_state",
    "/spark/session/teleop_active",
    "/spark/cameras/lightning/wrist_1/color/image_raw",
    "/spark/cameras/world/scene_1/color/image_raw"
  ]
}
```


## Workflow

1. fill session metadata
2. choose the sensors file
3. discover devices
4. adjust `Record` and `Role` for discovered devices
5. start the session
6. validate once
7. record multiple episodes under that same session profile
8. choose the published dataset target only when converting

If the rig setup changes materially, start a new session.


## UI Rules

The operator console should expose only:

- session metadata
- discovered devices
- subsystem health
- actions
- post-take episode notes

The main device table should show discovered devices only, with:

- `Record`
- `Kind`
- `Model`
- `Identifier`
- `Role`

It must not expose:

- fake devices from presets
- overlay labels
- expected-vs-missing device panes
- publishable/blocked profile matrices
- raw topic checkboxes in the main workflow


## Important Boundary

The session profile decides what one session records.

It does not redefine the shared contract, it does not change the canonical V2 topic surface, and it does not choose the published dataset folder up front.
