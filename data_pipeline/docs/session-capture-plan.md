# Session Model And Device Discovery

## Purpose

This document defines the session-level object used by the operator console and
raw recorder.

The session model keeps only three concepts:

- the shared topic contract
- the local sensors file
- one resolved session state

Everything else that had grown around this, such as expected-device lists and
profile-compatibility matrices, is intentionally out of the main workflow.


## Why The Session Model Exists

The session model exists because the operator UI is not itself the durable
recording contract.

The pipeline needs one resolved object that answers:

- what this session is trying to record
- which discovered devices are included
- which canonical sensor keys those devices map to
- which raw topics the recorder should actually capture

That resolved object is simpler and more durable than trying to infer the full
session intent later from:

- ad hoc UI state
- mutable local files
- or whichever devices happened to be visible at one later moment


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

- canonical topic names
- canonical sensor keys
- timestamp meanings
- dataset-facing semantics

See [Topic Contract](./topic-contract.md).

### Sensors file

The sensors file is the one local rig file.

Its main job is:

- serial or device-path to canonical-sensor-key mapping

Solved camera geometry is a separate local file, not something the operator should type into the console state.

Why this matters:

- device identity and solved geometry are not the same thing
- the sensors file should stay simple enough to act as a safe default map
- calibration belongs in its own subsystem

### Presets file

The operator console may load or save a presets file for later reuse.

That file stores session-level defaults such as:

- task metadata
- active arms
- remembered device selections

It does not replace the sensors file.

The checked-in starting point is:

- `data_pipeline/configs/operator_console_presets.example.yaml`

The presets file is a convenience artifact, not a shared contract object.

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


## Why Published Profiles Do Not Define The Live Session

Published conversion policy and live session setup are intentionally separate.

The published profile answers things like:

- output frame rate
- alignment rules
- missing-data policy

It should not be the thing that decides:

- which physical devices are present today
- which discovered devices are recorded this session
- which canonical sensor key a specific serial or device path should use today

That separation is why the console can stay discovery-first while conversion
still uses one generic checked-in policy.


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
in [Topic Contract](./topic-contract.md), not add a second alias layer.

Sensor-key choices are constrained by device kind:

- `realsense` may use only camera sensor keys
- `gelsight` may use only tactile sensor keys


## Session State Shape

Example:

```json
{
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
4. adjust `Record` and `Sensor Key` for discovered devices
5. start the session
6. record multiple episodes under that same session state
7. choose the published dataset target only when converting

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
- `Device`
- `Hardware ID`
- `Sensor Key`

`Hardware ID` is only the runtime display value for the discovered device:

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

It does not redefine the shared contract, it does not change the canonical
topic surface, and it does not choose the published dataset folder up front.

That last point is important:

- published folder choice is a later artifact decision
- the session model should describe recording truth, not dataset naming policy
