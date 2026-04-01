# Session State V2

## Purpose

This document defines the session-level object used by the operator console and raw recorder.

V2 keeps only three concepts here:

- the shared topic contract
- the local sensors file
- one resolved session state

Everything else that had grown around this, such as expected-device lists and
profile-compatibility matrices, is intentionally out of the main workflow.


## Ground Rules

### Discovery is truth

If a device is not discovered, it is not part of the live session.

### The sensors file provides defaults, not fake devices

The sensors file may tell the system:

- which serial or device path usually maps to which canonical sensor key

It does not create live devices.

### One session has one fixed setup

At session start, the operator chooses:

- session metadata
- which discovered devices are recorded
- which canonical sensor key each recorded device uses

All episodes in that session inherit the same setup.

### Operators confirm intent, not topic meaning

Operators may change:

- whether a discovered device is recorded
- which allowed canonical sensor key a discovered device uses

Operators do not redefine:

- canonical sensor keys
- topic names
- timestamp semantics


## Core Objects

### Shared contract

The shared contract defines:

- canonical V2 topic names
- canonical sensor keys
- timestamp meanings
- dataset-facing semantics

See [topic-contract.md](./topic-contract.md).

### Sensors file

The sensors file is the one local rig file.

Its main job is:

- serial or device-path to canonical-sensor-key mapping

Solved camera geometry is a separate local file, not something the operator should type into the console state.

### Presets file

The operator console may load or save a presets file for later reuse.

That file stores session-level defaults such as:

- task metadata
- active arms
- remembered device selections

It does not replace the sensors file.

The checked-in starting point is:

- `data_pipeline/configs/operator_console_presets.example.yaml`

### Session state

The resolved session state is the session truth.

It contains:

- `session_id`
- `active_arms`
- `sensors_file`
- resolved `devices`
- resolved `selected_topics`

The operator may save presets for later reuse, but the active session state is
still derived from:

- the chosen presets file
- the chosen sensors file
- live device discovery


## Canonical Sensor Keys

Sensor keys are the canonical topic-prefix identities for sensors.

Examples:

- `/spark/cameras/lightning/wrist_1`
- `/spark/cameras/thunder/wrist_1`
- `/spark/cameras/world/scene_1`
- `/spark/cameras/world/scene_2`
- `/spark/tactile/lightning/finger_left`
- `/spark/tactile/thunder/finger_right`

The naming scheme is extensible. New keys should follow the shared topic grammar
in [topic-contract.md](./topic-contract.md), not add a second alias layer.

Sensor-key choices are constrained by device kind:

- `realsense` may use only camera sensor keys
- `gelsight` may use only tactile sensor keys


## Session State Shape

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
      "serial_number": "130322273305",
      "sensor_key": "/spark/cameras/lightning/wrist_1",
      "enabled": true
    },
    {
      "kind": "realsense",
      "serial_number": "213622251272",
      "sensor_key": "/spark/cameras/world/scene_1",
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
4. adjust `Record` and `Sensor` for discovered devices
5. start the session
6. validate once
7. record multiple episodes under that same session state
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
- `Identifier`
- `Sensor`

`Identifier` is only the runtime display value for the discovered device:

- RealSense: serial number
- GelSight: device path

It is not part of the canonical sensor identity model.

It must not expose:

- fake devices from presets
- expected-vs-missing device panes
- publishable/blocked profile matrices
- raw topic checkboxes in the main workflow


## Important Boundary

The session state decides what one session records.

It does not redefine the shared contract, it does not change the canonical V2 topic surface, and it does not choose the published dataset folder up front.
